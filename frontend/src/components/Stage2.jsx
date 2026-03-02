import { useState } from 'react';
import Markdown from './Markdown';
import './Stage2.css';

function deAnonymizeText(text, labelToModel) {
  if (!labelToModel) return text;

  let result = text;
  // Replace each "Response X" with the actual model name
  Object.entries(labelToModel).forEach(([label, model]) => {
    const modelShortName = model.split('/')[1] || model;
    result = result.replace(new RegExp(label, 'g'), `**${modelShortName}**`);
  });
  return result;
}

function getScoreBadgeClass(score) {
  if (score === null || score === undefined) return 'score-badge';
  if (score >= 4.0) return 'score-badge score-good';
  if (score >= 3.0) return 'score-badge score-avg';
  return 'score-badge score-poor';
}

function shortModel(model) {
  return model.split('/')[1] || model;
}

// Detect legacy format (has parsed_ranking instead of parsed_scores)
function isLegacyFormat(evaluations) {
  if (!evaluations || evaluations.length === 0) return false;
  return 'parsed_ranking' in evaluations[0] && !('parsed_scores' in evaluations[0]);
}

export default function Stage2({ evaluations, axes, labelToModel, aggregateScores }) {
  const [activeTab, setActiveTab] = useState(0);

  // Support legacy prop name
  const data = evaluations;

  if (!data || data.length === 0) {
    return null;
  }

  // Legacy ranking format — render old-style UI
  if (isLegacyFormat(data)) {
    return <LegacyStage2 rankings={data} labelToModel={labelToModel} />;
  }

  return (
    <div className="stage stage2">
      <h3 className="stage-title">Stage 2: Peer Scoring</h3>

      {/* Axes display */}
      {axes && axes.length > 0 && (
        <div className="axes-section">
          <h4>Evaluation Axes</h4>
          <p className="stage-description">
            The chairman selected these criteria based on the question type:
          </p>
          <div className="axes-list">
            {axes.map((axis, i) => (
              <div key={i} className="axis-item">
                <span className="axis-name">{axis.name}</span>
                <span className="axis-description">{axis.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Score matrix */}
      {aggregateScores && aggregateScores.length > 0 && axes && (
        <div className="score-matrix-section">
          <h4>Score Matrix</h4>
          <p className="stage-description">
            Average scores across all peer evaluations (1-5 scale, higher is better):
          </p>
          <div className="score-matrix-wrapper">
            <table className="score-matrix">
              <thead>
                <tr>
                  <th className="matrix-rank-col">#</th>
                  <th className="matrix-model-col">Model</th>
                  {axes.map((axis, i) => (
                    <th key={i} className="matrix-axis-col">{axis.name}</th>
                  ))}
                  <th className="matrix-overall-col">Overall</th>
                </tr>
              </thead>
              <tbody>
                {aggregateScores.map((agg, index) => (
                  <tr key={index}>
                    <td className="matrix-rank">#{index + 1}</td>
                    <td className="matrix-model">{shortModel(agg.model)}</td>
                    {axes.map((axis, i) => {
                      const score = agg.axis_scores?.[axis.name];
                      return (
                        <td key={i}>
                          <span className={getScoreBadgeClass(score)}>
                            {score !== null && score !== undefined ? score.toFixed(1) : '—'}
                          </span>
                        </td>
                      );
                    })}
                    <td>
                      <span className={getScoreBadgeClass(agg.overall_score)}>
                        <strong>{agg.overall_score.toFixed(2)}</strong>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Shuffle order */}
      {labelToModel && Object.keys(labelToModel).length > 0 && (
        <div className="shuffle-order">
          <strong>Shuffle Order:</strong>{' '}
          {Object.entries(labelToModel).map(([label, model], i) => (
            <span key={label}>
              {label} = {shortModel(model)}
              {i < Object.keys(labelToModel).length - 1 ? ', ' : ''}
            </span>
          ))}
        </div>
      )}

      {/* Raw evaluations tabs */}
      <h4>Raw Evaluations</h4>
      <p className="stage-description">
        Each model evaluated all responses (anonymized as Response A, B, C, etc.) and provided scores.
        Below, model names are shown in <strong>bold</strong> for readability, but the original evaluation used anonymous labels.
      </p>

      <div className="tabs">
        {data.map((evaluation, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {shortModel(evaluation.model)}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="ranking-model">
          {data[activeTab].model}
        </div>
        <div className="ranking-content markdown-content">
          <Markdown>
            {deAnonymizeText(data[activeTab].evaluation, labelToModel)}
          </Markdown>
        </div>

        {/* Extracted scores */}
        {data[activeTab].parsed_scores &&
         Object.keys(data[activeTab].parsed_scores).length > 0 && (
          <div className="parsed-scores">
            <strong>Extracted Scores:</strong>
            <div className="extracted-scores-list">
              {Object.entries(data[activeTab].parsed_scores).map(([label, axisScores]) => (
                <div key={label} className="extracted-score-row">
                  <span className="extracted-label">
                    {labelToModel && labelToModel[label]
                      ? shortModel(labelToModel[label])
                      : label}:
                  </span>
                  <span className="extracted-axes">
                    {Object.entries(axisScores).map(([axis, score], i) => (
                      <span key={axis} className={getScoreBadgeClass(score)}>
                        {axis}={score}
                        {i < Object.entries(axisScores).length - 1 ? ' ' : ''}
                      </span>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Legacy component for old ranking-based data
function LegacyStage2({ rankings, labelToModel }) {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <div className="stage stage2">
      <h3 className="stage-title">Stage 2: Peer Rankings</h3>

      <h4>Raw Evaluations</h4>
      <p className="stage-description">
        Each model evaluated all responses (anonymized as Response A, B, C, etc.) and provided rankings.
        Below, model names are shown in <strong>bold</strong> for readability, but the original evaluation used anonymous labels.
      </p>

      {labelToModel && Object.keys(labelToModel).length > 0 && (
        <div className="shuffle-order">
          <strong>Shuffle Order:</strong>{' '}
          {Object.entries(labelToModel).map(([label, model], i) => (
            <span key={label}>
              {label} = {shortModel(model)}
              {i < Object.keys(labelToModel).length - 1 ? ', ' : ''}
            </span>
          ))}
        </div>
      )}

      <div className="tabs">
        {rankings.map((rank, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {shortModel(rank.model)}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="ranking-model">
          {rankings[activeTab].model}
        </div>
        <div className="ranking-content markdown-content">
          <Markdown>
            {deAnonymizeText(rankings[activeTab].ranking, labelToModel)}
          </Markdown>
        </div>

        {rankings[activeTab].parsed_ranking &&
         rankings[activeTab].parsed_ranking.length > 0 && (
          <div className="parsed-ranking">
            <strong>Extracted Ranking:</strong>
            <ol>
              {rankings[activeTab].parsed_ranking.map((label, i) => (
                <li key={i}>
                  {labelToModel && labelToModel[label]
                    ? shortModel(labelToModel[label])
                    : label}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  );
}
