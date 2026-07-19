/** Alias — redirects /stock/:ticker/report to the unified stock page report section. */
import { Navigate, useParams } from 'react-router-dom';

export function ResearchReportPage() {
  const { ticker = '' } = useParams();
  const t = ticker.toUpperCase();
  if (!t) return <Navigate to="/" replace />;
  return <Navigate to={`/stock/${t}#report`} replace />;
}
