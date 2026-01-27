import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const draftSaveRef = useRef({ timer: null, id: null, draft: '' });
  const isResizingRef = useRef(false);

  const sortConversations = (list) => {
    const sorted = [...list];
    sorted.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    sorted.sort((a, b) => {
      if (a.pinned === b.pinned) return 0;
      return a.pinned ? -1 : 1;
    });
    return sorted;
  };

  // Load conversations on mount
  useEffect(() => {
    loadConversations({ includeArchived: showArchived });
  }, [showArchived]);

  useEffect(() => {
    const handlePointerMove = (event) => {
      if (!isResizingRef.current) return;
      const minWidth = 220;
      const maxWidth = 420;
      const nextWidth = Math.min(maxWidth, Math.max(minWidth, event.clientX));
      setSidebarWidth(nextWidth);
    };

    const handlePointerUp = () => {
      if (!isResizingRef.current) return;
      isResizingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, []);

  const handleResizeStart = (event) => {
    event.preventDefault();
    isResizingRef.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async ({ includeArchived = showArchived } = {}) => {
    try {
      const convs = await api.listConversations({ includeArchived });
      setConversations(sortConversations(convs));
      if (currentConversationId) {
        const exists = convs.some((conv) => conv.id === currentConversationId);
        if (!exists) {
          try {
            await api.getConversation(currentConversationId);
          } catch (error) {
            setCurrentConversationId(null);
            setCurrentConversation(null);
          }
        }
      }
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
      setCurrentConversationId(null);
      setCurrentConversation(null);
    }
  };

  const flushDraft = async () => {
    const pending = draftSaveRef.current;
    if (pending.timer) {
      clearTimeout(pending.timer);
      draftSaveRef.current.timer = null;
      if (pending.id) {
        try {
          await api.updateConversation(pending.id, { draft: pending.draft });
        } catch (error) {
          console.error('Failed to save draft:', error);
        }
      }
    }
  };

  const scheduleDraftSave = (conversationId, draft) => {
    if (!conversationId) return;
    if (draftSaveRef.current.timer) {
      clearTimeout(draftSaveRef.current.timer);
    }
    draftSaveRef.current = { timer: null, id: conversationId, draft };
    draftSaveRef.current.timer = setTimeout(async () => {
      try {
        await api.updateConversation(conversationId, { draft });
      } catch (error) {
        console.error('Failed to save draft:', error);
      }
    }, 400);
  };

  const isEmptyConversation = (conv) => {
    if (!conv) return false;
    const draft = (conv.draft || '').trim();
    return (conv.messages?.length || 0) === 0 && draft === '';
  };

  const cleanupEmptyConversation = async (conv) => {
    if (!conv || !isEmptyConversation(conv)) return;
    try {
      await api.deleteConversation(conv.id);
      setConversations((prev) => prev.filter((item) => item.id !== conv.id));
      if (currentConversationId === conv.id) {
        setCurrentConversationId(null);
        setCurrentConversation(null);
      }
    } catch (error) {
      console.error('Failed to delete empty conversation:', error);
    }
  };

  const handleNewConversation = async () => {
    try {
      await flushDraft();
      await cleanupEmptyConversation(currentConversation);
      const newConv = await api.createConversation();
      setConversations((prev) => sortConversations([
        {
          id: newConv.id,
          created_at: newConv.created_at,
          message_count: 0,
          pinned: newConv.pinned,
          archived: newConv.archived,
          has_draft: false,
          title: newConv.title,
        },
        ...prev,
      ]));
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = async (id) => {
    await flushDraft();
    if (currentConversationId && currentConversationId !== id) {
      await cleanupEmptyConversation(currentConversation);
    }
    setCurrentConversationId(id);
  };

  const handleDraftChange = (draft) => {
    if (!currentConversationId) return;
    setCurrentConversation((prev) =>
      prev ? { ...prev, draft } : prev
    );
    setConversations((prev) =>
      prev.map((conv) =>
        conv.id === currentConversationId
          ? { ...conv, has_draft: Boolean(draft.trim()) }
          : conv
      )
    );
    if (currentConversation?.messages?.length === 0) {
      scheduleDraftSave(currentConversationId, draft);
    }
  };

  const handleTogglePin = async (id, pinned) => {
    try {
      const updated = await api.updateConversation(id, { pinned });
      setConversations((prev) =>
        sortConversations(
          prev.map((conv) => (conv.id === id ? { ...conv, pinned } : conv))
        )
      );
      if (currentConversationId === id) {
        setCurrentConversation(updated);
      }
      loadConversations({ includeArchived: showArchived });
    } catch (error) {
      console.error('Failed to update pin:', error);
    }
  };

  const handleToggleArchive = async (id, archived) => {
    try {
      const updates = archived ? { archived: true, pinned: false } : { archived: false };
      const updated = await api.updateConversation(id, updates);
      setConversations((prev) => {
        const mapped = prev.map((conv) =>
          conv.id === id
            ? { ...conv, archived: updated.archived, pinned: updated.pinned }
            : conv
        );
        if (!showArchived && updated.archived) {
          return mapped.filter((conv) => conv.id !== id);
        }
        return sortConversations(mapped);
      });
      if (currentConversationId === id) {
        setCurrentConversation(updated);
      }
      loadConversations({ includeArchived: showArchived });
    } catch (error) {
      console.error('Failed to update archive:', error);
    }
  };

  const handleDeleteConversation = async (id) => {
    const confirmed = window.confirm('Delete this conversation? This cannot be undone.');
    if (!confirmed) {
      return;
    }
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((conv) => conv.id !== id));
      if (currentConversationId === id) {
        setCurrentConversationId(null);
        setCurrentConversation(null);
      }
      loadConversations({ includeArchived: showArchived });
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
        draft: '',
      }));
      setConversations((prev) =>
        prev.map((conv) =>
          conv.id === currentConversationId ? { ...conv, has_draft: false } : conv
        )
      );

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Send message with streaming
      await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
        switch (eventType) {
          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      });
    } catch (error) {
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onTogglePin={handleTogglePin}
        onToggleArchive={handleToggleArchive}
        onDeleteConversation={handleDeleteConversation}
        showArchived={showArchived}
        onToggleArchivedView={() => setShowArchived((prev) => !prev)}
        width={sidebarWidth}
      />
      <div
        className="sidebar-resizer"
        onPointerDown={handleResizeStart}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        onDraftChange={handleDraftChange}
        isLoading={isLoading}
      />
    </div>
  );
}

export default App;
