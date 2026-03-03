import { useState } from 'react';
import './ClarificationForm.css';

export default function ClarificationForm({ questions, onSubmit, onSkip }) {
  const [answers, setAnswers] = useState(questions.map(() => ''));

  const handleSubmit = (e) => {
    e.preventDefault();
    const result = questions.map((q, i) => ({ question: q, answer: answers[i] }));
    onSubmit(result);
  };

  return (
    <div className="clarification-form">
      <div className="clarification-header">
        <span className="clarification-icon">&#x1F4AC;</span>
        <span>The Chairman has a few questions to better understand your query:</span>
      </div>
      <form onSubmit={handleSubmit}>
        {questions.map((question, i) => (
          <div key={i} className="clarification-question">
            <label className="clarification-label">{question}</label>
            <textarea
              className="clarification-input"
              value={answers[i]}
              onChange={(e) => {
                const next = [...answers];
                next[i] = e.target.value;
                setAnswers(next);
              }}
              rows={2}
              placeholder="Your answer..."
            />
          </div>
        ))}
        <div className="clarification-actions">
          <button type="submit" className="clarification-submit">
            Submit Answers
          </button>
          <button type="button" className="clarification-skip" onClick={onSkip}>
            Skip (proceed without clarification)
          </button>
        </div>
      </form>
    </div>
  );
}
