import './Stage0.css';

export default function Stage0({ originalQuery, rewrittenQuery }) {
  if (!rewrittenQuery) return null;

  return (
    <div className="stage0-container">
      <div className="stage0-header">Query Refinement</div>
      {originalQuery && originalQuery !== rewrittenQuery && (
        <div className="stage0-original">
          <span className="stage0-original-label">Original:</span> {originalQuery}
        </div>
      )}
      <div className="stage0-rewritten">{rewrittenQuery}</div>
    </div>
  );
}
