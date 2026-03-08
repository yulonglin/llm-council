import { useState, useEffect, useRef } from 'react';
import Markdown from './Markdown';
import Stage0 from './Stage0';
import ClarificationForm from './ClarificationForm';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import './ChatInterface.css';

export default function ChatInterface({
  conversation,
  onSendMessage,
  onDraftChange,
  isLoading,
  onClarificationSubmit,
  onCancel,
  queryRewriteEnabled,
  onToggleQueryRewrite,
}) {
  const [input, setInput] = useState('');
  const messagesContainerRef = useRef(null);

  const scrollToBottom = () => {
    if (messagesContainerRef.current) {
      messagesContainerRef.current.scrollTop =
        messagesContainerRef.current.scrollHeight;
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  useEffect(() => {
    setInput(conversation?.draft || '');
  }, [conversation?.id]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input);
      setInput('');
      onDraftChange?.('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const copyToClipboard = async (text, label = 'Content') => {
    try {
      await navigator.clipboard.writeText(text);
      // Could show a toast here, but for now we'll just rely on user action
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const formatThreadMarkdown = () => {
    if (!conversation?.messages) return '';
    
    return conversation.messages.map((msg, index) => {
      const role = msg.role === 'user' ? 'USER' : 'LLM COUNCIL';
      let content = msg.content || '';
      
      if (msg.role === 'assistant') {
        if (msg.rewrittenQuery) {
          content = `**[Rewritten query: ${msg.rewrittenQuery}]**\n\n`;
        }
        if (msg.stage3) {
          content += typeof msg.stage3 === 'string' ? msg.stage3 : msg.stage3.response || JSON.stringify(msg.stage3);
        } else if (msg.stage1) {
          content += '(Incomplete response)';
        }
      }
      
      return `### Message ${index} - ${role}\n\n${content}\n`;
    }).join('\n---\n\n');
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <div className="header-info">
          <h3 className="header-title">{conversation.title || 'New Conversation'}</h3>
          <div className="header-meta">
            <span>ID: {conversation.id}</span>
            <button 
              className="copy-id-btn"
              onClick={() => copyToClipboard(conversation.id, 'ID')}
              title="Copy ID"
            >
              (Copy)
            </button>
          </div>
        </div>
        <div className="header-actions">
          <button 
            className="secondary-button"
            onClick={() => copyToClipboard(formatThreadMarkdown(), 'Thread')}
            title="Copy full thread as Markdown"
          >
            Copy Thread
          </button>
        </div>
      </div>

      <div className="messages-container" ref={messagesContainerRef}>
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-header">
                    <div className="message-label">You</div>
                    <div className="message-meta">
                      <span className="message-id">Msg #{index}</span>
                      <button 
                        className="message-action"
                        onClick={() => copyToClipboard(msg.content)}
                      >
                        Copy
                      </button>
                    </div>
                  </div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <Markdown>{msg.content}</Markdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-header">
                    <div className="message-label">LLM Council</div>
                    <div className="message-meta">
                      <span className="message-id">Msg #{index}</span>
                      <button 
                        className="message-action"
                        onClick={() => {
                          const content = msg.stage3 
                            ? (typeof msg.stage3 === 'string' ? msg.stage3 : msg.stage3.response)
                            : '';
                          if (content) copyToClipboard(content);
                        }}
                        disabled={!msg.stage3}
                      >
                        Copy Final
                      </button>
                    </div>
                  </div>

                  {/* Stage 0 - Query refinement */}
                  {msg.loading?.stage0 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Analyzing query...</span>
                    </div>
                  )}
                  {msg.rewrittenQuery && (
                    <Stage0
                      originalQuery={conversation.messages[index - 1]?.content}
                      rewrittenQuery={msg.rewrittenQuery}
                    />
                  )}
                  {msg.clarificationQuestions && !isLoading && (
                    <ClarificationForm
                      questions={msg.clarificationQuestions}
                      onSubmit={onClarificationSubmit}
                      onSkip={() => onClarificationSubmit(msg.clarificationQuestions.map(q => ({ question: q, answer: '' })))}
                    />
                  )}

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer scoring...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      evaluations={msg.stage2}
                      axes={msg.axes || msg.metadata?.axes}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateScores={msg.metadata?.aggregate_scores}
                    />
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} />}

                  {msg.cancelled && (
                    <div className="cancelled-indicator">
                      Council run was cancelled.
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
            <button className="cancel-button" onClick={onCancel}>
              Cancel
            </button>
          </div>
        )}

      </div>

      {conversation.messages.length === 0 && (
        <form className="input-form" onSubmit={handleSubmit}>
          <textarea
            className="message-input"
            placeholder="Ask your question... (Shift+Enter for new line, Enter to send)"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              onDraftChange?.(e.target.value);
            }}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={3}
          />
          <div className="input-actions">
            <label className="rewrite-toggle" title="When enabled, the chairman rewrites your query for clarity before the council answers">
              <input
                type="checkbox"
                checked={queryRewriteEnabled}
                onChange={onToggleQueryRewrite}
              />
              <span className="rewrite-toggle-label">Rewrite query</span>
            </label>
            <button
              type="submit"
              className="send-button"
              disabled={!input.trim() || isLoading}
            >
              Send
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
