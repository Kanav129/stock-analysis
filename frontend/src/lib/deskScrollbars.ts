/** Overlay scrollbars for the desk.

Native CSS cannot fade a thumb after scrolling stops (and styling
::-webkit-scrollbar disables overlay auto-hide). This draws a thin fixed
thumb on document.body, shows it while scrolling, then fades it out.
Wheel, trackpad, and keyboard scrolling stay on the real element.
*/

/** Fully visible after the last scroll event, before the fade-out starts. */
const HOLD_MS = 1500;
const MIN_THUMB = 24;
const HIT = 12;
const INSET = 2;
const FLAG = '__deskScrollbars';

type Axis = 'x' | 'y';

type Metrics = {
  viewport: boolean;
  rtl: boolean;
  borderTop: number;
  borderRight: number;
  borderBottom: number;
  borderLeft: number;
};

type Track = {
  el: HTMLElement;
  axis: Axis;
  thumb: HTMLDivElement;
  hideTimer: number;
  hovering: boolean;
  dragging: boolean;
  /** True once the thumb has been painted at opacity 0, so the next class change can fade. */
  painted: boolean;
  priming: boolean;
  wantsOn: boolean;
};

type Bucket = {
  x?: Track;
  y?: Track;
  metrics: Metrics;
  ro: ResizeObserver;
};

const buckets = new Map<HTMLElement, Bucket>();

function isFormControl(el: HTMLElement): boolean {
  return (
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement ||
    el instanceof HTMLInputElement
  );
}

function resolveScroller(target: EventTarget | null): HTMLElement | null {
  if (target === document || target === document.documentElement || target === document.body) {
    const scroller = document.scrollingElement;
    return scroller instanceof HTMLElement ? scroller : null;
  }
  return target instanceof HTMLElement ? target : null;
}

function readMetrics(el: HTMLElement): Metrics {
  const viewport = el === document.scrollingElement;
  if (viewport) {
    return {
      viewport: true,
      rtl: document.documentElement.dir === 'rtl',
      borderTop: 0,
      borderRight: 0,
      borderBottom: 0,
      borderLeft: 0,
    };
  }
  const style = getComputedStyle(el);
  return {
    viewport: false,
    rtl: style.direction === 'rtl',
    borderTop: Number.parseFloat(style.borderTopWidth) || 0,
    borderRight: Number.parseFloat(style.borderRightWidth) || 0,
    borderBottom: Number.parseFloat(style.borderBottomWidth) || 0,
    borderLeft: Number.parseFloat(style.borderLeftWidth) || 0,
  };
}

function isScrollOverflow(value: string): boolean {
  return value === 'auto' || value === 'scroll' || value === 'overlay';
}

function removeTrack(track: Track): void {
  window.clearTimeout(track.hideTimer);
  track.thumb.remove();
  const bucket = buckets.get(track.el);
  if (!bucket) return;
  if (bucket[track.axis] === track) bucket[track.axis] = undefined;
  if (!bucket.x && !bucket.y) {
    bucket.ro.disconnect();
    buckets.delete(track.el);
  }
}

function dismiss(track: Track): void {
  track.wantsOn = false;
  window.clearTimeout(track.hideTimer);
  track.thumb.classList.remove('is-on');
}

function place(track: Track): boolean {
  const { el, axis, thumb } = track;
  const bucket = buckets.get(el);
  if (!bucket || !el.isConnected) {
    dismiss(track);
    return false;
  }
  const metrics = bucket.metrics;
  const rect = metrics.viewport
    ? new DOMRect(0, 0, window.innerWidth, window.innerHeight)
    : el.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) {
    dismiss(track);
    return false;
  }

  const client = axis === 'y' ? el.clientHeight : el.clientWidth;
  const scroll = axis === 'y' ? el.scrollHeight : el.scrollWidth;
  const pos = axis === 'y' ? el.scrollTop : el.scrollLeft;
  const max = scroll - client;
  if (max <= 2) {
    dismiss(track);
    return false;
  }

  if (axis === 'y') {
    const portTop = rect.top + metrics.borderTop;
    const portBottom = portTop + client;
    const visTop = Math.max(portTop, 0);
    let visBottom = Math.min(portBottom, window.innerHeight);
    if (bucket.x) visBottom -= HIT;
    const vis = visBottom - visTop;
    if (vis < MIN_THUMB) {
      dismiss(track);
      return false;
    }
    const thumbLen = Math.min(vis, Math.max(MIN_THUMB, (client / scroll) * vis));
    const along = (pos / max) * (vis - thumbLen);
    thumb.style.top = `${visTop + along}px`;
    thumb.style.height = `${thumbLen}px`;
    thumb.style.width = `${HIT}px`;
    thumb.style.bottom = 'auto';
    if (metrics.rtl) {
      const leftEdge = Math.max(rect.left + metrics.borderLeft, 0);
      thumb.style.left = `${leftEdge + INSET}px`;
      thumb.style.right = 'auto';
    } else {
      const rightEdge = Math.min(rect.right - metrics.borderRight, window.innerWidth);
      thumb.style.right = `${Math.max(0, window.innerWidth - rightEdge + INSET)}px`;
      thumb.style.left = 'auto';
    }
    return true;
  }

  const portLeft = rect.left + metrics.borderLeft;
  const portRight = portLeft + client;
  const visLeft = Math.max(portLeft, 0);
  const visRight = Math.min(portRight, window.innerWidth);
  const vis = visRight - visLeft;
  if (vis < MIN_THUMB) {
    dismiss(track);
    return false;
  }
  const thumbLen = Math.min(vis, Math.max(MIN_THUMB, (client / scroll) * vis));
  const along = (pos / max) * (vis - thumbLen);
  const bottomEdge = Math.min(rect.bottom - metrics.borderBottom, window.innerHeight);
  thumb.style.left = `${visLeft + along}px`;
  thumb.style.width = `${thumbLen}px`;
  thumb.style.height = `${HIT}px`;
  thumb.style.bottom = `${Math.max(0, window.innerHeight - bottomEdge + INSET)}px`;
  thumb.style.top = 'auto';
  thumb.style.right = 'auto';
  return true;
}

function holdMs(): number {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return 0;
  return HOLD_MS;
}

function finishReveal(track: Track): void {
  if (!track.wantsOn) return;
  track.thumb.classList.add('is-on');
  if (track.hovering || track.dragging) return;
  track.hideTimer = window.setTimeout(() => {
    if (track.hovering || track.dragging) return;
    track.wantsOn = false;
    track.thumb.classList.remove('is-on');
  }, holdMs());
}

function reveal(track: Track): void {
  track.wantsOn = true;
  window.clearTimeout(track.hideTimer);
  // The thumb is inserted in the same turn as the first scroll. Adding .is-on
  // immediately skips the opacity transition, so wait until it has painted at 0.
  if (!track.painted) {
    if (!track.priming) {
      track.priming = true;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          track.painted = true;
          track.priming = false;
          finishReveal(track);
        });
      });
    }
    return;
  }
  finishReveal(track);
}

function ensureBucket(el: HTMLElement): Bucket {
  const existing = buckets.get(el);
  if (existing) return existing;
  const bucket: Bucket = {
    metrics: readMetrics(el),
    ro: new ResizeObserver(() => {
      const current = buckets.get(el);
      if (!current) return;
      current.metrics = readMetrics(el);
      if (current.y) place(current.y);
      if (current.x) place(current.x);
    }),
  };
  bucket.ro.observe(el);
  buckets.set(el, bucket);
  return bucket;
}

function ensureTrack(el: HTMLElement, axis: Axis): Track {
  const bucket = ensureBucket(el);
  const existing = bucket[axis];
  if (existing) return existing;
  const thumb = document.createElement('div');
  thumb.className = `desk-scroll-thumb desk-scroll-thumb--${axis}`;
  thumb.dataset.deskScrollThumb = axis;
  thumb.setAttribute('aria-hidden', 'true');
  const track: Track = {
    el,
    axis,
    thumb,
    hideTimer: 0,
    hovering: false,
    dragging: false,
    painted: false,
    priming: false,
    wantsOn: false,
  };
  thumb.addEventListener('pointerenter', () => {
    track.hovering = true;
    reveal(track);
  });
  thumb.addEventListener('pointerleave', () => {
    track.hovering = false;
    reveal(track);
  });
  thumb.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    // The thumb lives on body so it is outside the directional dialog node.
    // Keep a drag on that list from counting as a click outside the overlay.
    if (el.closest('.desk-overlay, [role="dialog"]')) event.stopPropagation();
    event.preventDefault();
    beginDrag(track, event);
  });
  document.body.appendChild(thumb);
  bucket[axis] = track;
  return track;
}

function beginDrag(track: Track, event: PointerEvent): void {
  track.dragging = true;
  track.thumb.classList.add('is-dragging');
  document.documentElement.classList.add('desk-scroll-dragging');
  track.thumb.setPointerCapture(event.pointerId);
  const start = track.axis === 'y' ? event.clientY : event.clientX;
  const startScroll = track.axis === 'y' ? track.el.scrollTop : track.el.scrollLeft;
  const client = track.axis === 'y' ? track.el.clientHeight : track.el.clientWidth;
  const scrollSize = track.axis === 'y' ? track.el.scrollHeight : track.el.scrollWidth;
  const max = Math.max(0, scrollSize - client);
  const thumbLen = track.axis === 'y' ? track.thumb.offsetHeight : track.thumb.offsetWidth;
  const travel = Math.max(1, client - thumbLen);
  const scale = max / travel;

  const move = (ev: PointerEvent) => {
    const now = track.axis === 'y' ? ev.clientY : ev.clientX;
    const next = startScroll + (now - start) * scale;
    if (track.axis === 'y') track.el.scrollTop = next;
    else track.el.scrollLeft = next;
  };
  const end = (ev: PointerEvent) => {
    track.dragging = false;
    track.thumb.classList.remove('is-dragging');
    document.documentElement.classList.remove('desk-scroll-dragging');
    if (track.thumb.hasPointerCapture(ev.pointerId)) {
      track.thumb.releasePointerCapture(ev.pointerId);
    }
    track.thumb.removeEventListener('pointermove', move);
    track.thumb.removeEventListener('pointerup', end);
    track.thumb.removeEventListener('pointercancel', end);
    reveal(track);
  };
  track.thumb.addEventListener('pointermove', move);
  track.thumb.addEventListener('pointerup', end);
  track.thumb.addEventListener('pointercancel', end);
}

function syncEl(el: HTMLElement): void {
  if (!el.isConnected || isFormControl(el) || el.dataset.deskScrollThumb != null) return;
  const viewport = el === document.scrollingElement;
  const style = getComputedStyle(el);
  const allowY = viewport || isScrollOverflow(style.overflowY);
  const allowX = isScrollOverflow(style.overflowX) || (viewport && el.scrollWidth > el.clientWidth + 2);
  if (!allowY && !allowX) {
    const bucket = buckets.get(el);
    if (bucket?.y) removeTrack(bucket.y);
    if (bucket?.x) removeTrack(bucket.x);
    return;
  }
  if (allowY && el.scrollHeight > el.clientHeight + 2) {
    place(ensureTrack(el, 'y'));
  } else {
    const y = buckets.get(el)?.y;
    if (y) removeTrack(y);
  }
  if (allowX && el.scrollWidth > el.clientWidth + 2) {
    place(ensureTrack(el, 'x'));
  } else {
    const x = buckets.get(el)?.x;
    if (x) removeTrack(x);
  }
}

function onScroll(event: Event): void {
  const el = resolveScroller(event.target);
  if (!el || isFormControl(el)) return;
  if (!buckets.has(el)) syncEl(el);
  const bucket = buckets.get(el);
  if (!bucket) return;
  if (bucket.y && place(bucket.y)) reveal(bucket.y);
  if (bucket.x && place(bucket.x)) reveal(bucket.x);
  if (el === document.scrollingElement) {
    for (const [other, otherBucket] of buckets) {
      if (other === el) continue;
      if (otherBucket.y?.thumb.classList.contains('is-on')) place(otherBucket.y);
      if (otherBucket.x?.thumb.classList.contains('is-on')) place(otherBucket.x);
    }
  }
}

function prune(): void {
  for (const el of [...buckets.keys()]) {
    if (!el.isConnected) {
      const bucket = buckets.get(el);
      if (bucket?.y) removeTrack(bucket.y);
      if (bucket?.x) removeTrack(bucket.x);
    }
  }
}

export function installDeskScrollbars(): void {
  const win = window as Window & { [FLAG]?: boolean };
  if (win[FLAG]) return;
  win[FLAG] = true;

  document.addEventListener('scroll', onScroll, { capture: true, passive: true });
  window.addEventListener('resize', () => {
    for (const [el, bucket] of buckets) {
      bucket.metrics = readMetrics(el);
      if (bucket.y) place(bucket.y);
      if (bucket.x) place(bucket.x);
    }
  });

  let moveFrame = 0;
  document.addEventListener(
    'pointermove',
    () => {
      if (moveFrame) return;
      moveFrame = window.requestAnimationFrame(() => {
        moveFrame = 0;
        for (const bucket of buckets.values()) {
          if (bucket.y?.thumb.classList.contains('is-on')) place(bucket.y);
          if (bucket.x?.thumb.classList.contains('is-on')) place(bucket.x);
        }
      });
    },
    { passive: true },
  );

  let pruneTimer = 0;
  const observer = new MutationObserver(() => {
    window.clearTimeout(pruneTimer);
    pruneTimer = window.setTimeout(prune, 40);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  document.documentElement.classList.add('desk-scrollbars');
}
