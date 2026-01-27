import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onTogglePin,
  onToggleArchive,
  onDeleteConversation,
  showArchived,
  onToggleArchivedView,
  width,
}) {
  const pinned = conversations.filter((conv) => conv.pinned && !conv.archived);
  const unpinned = conversations.filter((conv) => !conv.pinned && !conv.archived);
  const archived = conversations.filter((conv) => conv.archived);

  const renderConversation = (conv) => (
    <div
      key={conv.id}
      className={`conversation-item ${
        conv.id === currentConversationId ? 'active' : ''
      }`}
      onClick={() => onSelectConversation(conv.id)}
    >
      <div className="conversation-row">
        <div className="conversation-info">
          <div className="conversation-title">
            {conv.title || 'New Conversation'}
          </div>
          <div className="conversation-meta">
            {conv.message_count} messages
            {conv.has_draft ? ' | Draft' : ''}
          </div>
        </div>
        <div className="conversation-actions">
          {!conv.archived && (
            <button
              className="conversation-action"
              onPointerDown={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePin(conv.id, !conv.pinned);
              }}
              title={conv.pinned ? 'Unpin' : 'Pin'}
              aria-label={conv.pinned ? 'Unpin conversation' : 'Pin conversation'}
              type="button"
            >
              {conv.pinned ? '📍' : '📌'}
            </button>
          )}
          <button
            className="conversation-action"
            onPointerDown={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onToggleArchive(conv.id, !conv.archived);
            }}
            title={conv.archived ? 'Restore' : 'Archive'}
            aria-label={conv.archived ? 'Restore conversation' : 'Archive conversation'}
            type="button"
          >
            {conv.archived ? '↩️' : '🗄️'}
          </button>
          <button
            className="conversation-action danger"
            onPointerDown={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onDeleteConversation(conv.id);
            }}
            title="Delete"
            aria-label="Delete conversation"
            type="button"
          >
            🗑️
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="sidebar" style={width ? { width } : undefined}>
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
        <button
          className="toggle-archived-btn"
          onClick={onToggleArchivedView}
        >
          {showArchived ? 'Hide Archived' : 'Show Archived'}
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          <>
            {pinned.length > 0 && (
              <>
                <div className="conversation-section">Pinned</div>
                {pinned.map(renderConversation)}
              </>
            )}
            {unpinned.length > 0 && (
              <>
                {pinned.length > 0 && (
                  <div className="conversation-section">Conversations</div>
                )}
                {unpinned.map(renderConversation)}
              </>
            )}
            {showArchived && archived.length > 0 && (
              <>
                <div className="conversation-section">Archived</div>
                {archived.map(renderConversation)}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
