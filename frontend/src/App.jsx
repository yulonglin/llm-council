import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [loadingConversationIds, setLoadingConversationIds] = useState(new Set());
  const activeStreamsRef = useRef(new Map()); // convId → AbortController
  const isCurrentLoading = loadingConversationIds.has(currentConversationId);
  const [showArchived, setShowArchived] = useState(false);
  const [queryRewriteEnabled, setQueryRewriteEnabled] = useState(true);
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

  // Unified SSE event handler for council stages (used by send, clarify, and reconnect)
  const handleCouncilEvent = (targetId, eventType, event) => {
    const updateLastMessage = (updater) => {
      setCurrentConversation((prev) => {
        if (!prev || prev.id !== targetId) return prev;
        const messages = [...prev.messages];
        const lastMsg = { ...messages[messages.length - 1] };
        const loading = { ...(lastMsg.loading || { stage0: false, stage1: false, stage2: false, stage3: false }) };
        updater(lastMsg, loading);
        lastMsg.loading = loading;
        messages[messages.length - 1] = lastMsg;
        return { ...prev, messages };
      });
    };

    switch (eventType) {
      case 'stage0_start':
        updateLastMessage((msg, loading) => { loading.stage0 = true; });
        break;
      case 'stage0_complete':
        updateLastMessage((msg, loading) => {
          msg.rewrittenQuery = event.data.rewritten_query;
          loading.stage0 = false;
        });
        break;
      case 'clarification_needed':
        updateLastMessage((msg, loading) => {
          msg.clarificationQuestions = event.data.questions;
          loading.stage0 = false;
        });
        setLoadingConversationIds(prev => {
          const next = new Set(prev);
          next.delete(targetId);
          return next;
        });
        activeStreamsRef.current.delete(targetId);
        break;
      case 'stage1_start':
        updateLastMessage((msg, loading) => { loading.stage1 = true; });
        break;
      case 'stage1_complete':
        updateLastMessage((msg, loading) => {
          msg.stage1 = event.data;
          loading.stage1 = false;
        });
        break;
      case 'axes_complete':
        updateLastMessage((msg) => { msg.axes = event.data; });
        break;
      case 'stage2_start':
        updateLastMessage((msg, loading) => { loading.stage2 = true; });
        break;
      case 'stage2_complete':
        updateLastMessage((msg, loading) => {
          msg.stage2 = event.data;
          msg.metadata = event.metadata;
          loading.stage2 = false;
        });
        break;
      case 'stage3_start':
        updateLastMessage((msg, loading) => { loading.stage3 = true; });
        break;
      case 'stage3_complete':
        updateLastMessage((msg, loading) => {
          msg.stage3 = event.data;
          loading.stage3 = false;
        });
        break;
      case 'title_complete':
        loadConversations();
        break;
      case 'complete':
        loadConversations();
        setLoadingConversationIds(prev => {
          const next = new Set(prev);
          next.delete(targetId);
          return next;
        });
        activeStreamsRef.current.delete(targetId);
        break;
      case 'error':
        console.error('Stream error:', event.message);
        setLoadingConversationIds(prev => {
          const next = new Set(prev);
          next.delete(targetId);
          return next;
        });
        activeStreamsRef.current.delete(targetId);
        break;
      case 'no_active_task':
        // Task finished before we subscribed — reload from storage
        loadConversation(targetId);
        setLoadingConversationIds(prev => {
          const next = new Set(prev);
          next.delete(targetId);
          return next;
        });
        activeStreamsRef.current.delete(targetId);
        break;
      default:
        console.log('Unknown event type:', eventType);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);

      // Check if there's a running council task to reconnect to
      const lastMsg = conv.messages?.[conv.messages.length - 1];
      if (lastMsg?.role === 'assistant' && lastMsg.status !== 'complete' && lastMsg.status !== 'error' && lastMsg.status !== 'cancelled') {
        // Already have a local stream for this conversation? Skip.
        if (activeStreamsRef.current.has(id)) return;

        const { running } = await api.getTaskStatus(id);
        if (running) {
          // Reconnect to the running task
          setLoadingConversationIds(prev => new Set(prev).add(id));
          const abortController = new AbortController();
          activeStreamsRef.current.set(id, abortController);

          api.subscribeToTask(id, (eventType, event) => {
            handleCouncilEvent(id, eventType, event);
          }, { signal: abortController.signal }).catch(err => {
            if (err.name !== 'AbortError') {
              console.error('Subscribe error:', err);
            }
          });
        } else {
          // Stale in-progress: server restarted. Show partial results.
          setCurrentConversation(prev => {
            if (!prev || prev.id !== id) return prev;
            const messages = [...prev.messages];
            const last = { ...messages[messages.length - 1] };
            last.stale = true;
            last.loading = { stage0: false, stage1: false, stage2: false, stage3: false };
            messages[messages.length - 1] = last;
            return { ...prev, messages };
          });
        }
      }
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
    // Abort any active stream for this conversation
    const controller = activeStreamsRef.current.get(id);
    if (controller) {
      controller.abort();
      activeStreamsRef.current.delete(id);
      setLoadingConversationIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
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

    const targetId = currentConversationId;

    // Add to loading set
    setLoadingConversationIds(prev => new Set(prev).add(targetId));

    // Create AbortController for this stream
    const abortController = new AbortController();
    activeStreamsRef.current.set(targetId, abortController);

    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => {
        if (!prev || prev.id !== targetId) return prev;
        return {
          ...prev,
          messages: [...prev.messages, userMessage],
          draft: '',
        };
      });
      setConversations((prev) =>
        prev.map((conv) =>
          conv.id === targetId ? { ...conv, has_draft: false } : conv
        )
      );

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage0: null,
        rewrittenQuery: null,
        clarificationQuestions: null,
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        loading: {
          stage0: false,
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => {
        if (!prev || prev.id !== targetId) return prev;
        return {
          ...prev,
          messages: [...prev.messages, assistantMessage],
        };
      });

      // Send message with streaming — uses unified event handler
      await api.sendMessageStream(targetId, content, (eventType, event) => {
        handleCouncilEvent(targetId, eventType, event);
      }, { signal: abortController.signal, skipRewrite: !queryRewriteEnabled });
    } catch (error) {
      if (error.name === 'AbortError') {
        // Stream was intentionally aborted (e.g., conversation deleted)
        return;
      }
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => {
        if (!prev || prev.id !== targetId) return prev;
        return {
          ...prev,
          messages: prev.messages.slice(0, -2),
        };
      });
      setLoadingConversationIds(prev => {
        const next = new Set(prev);
        next.delete(targetId);
        return next;
      });
      activeStreamsRef.current.delete(targetId);
    }
  };

  const handleCancelStream = () => {
    if (!currentConversationId) return;
    // Abort the local SSE subscriber
    const controller = activeStreamsRef.current.get(currentConversationId);
    if (controller) {
      controller.abort();
      activeStreamsRef.current.delete(currentConversationId);
    }
    // Cancel the background task on the server
    api.cancelTask(currentConversationId).catch(() => {});
    setLoadingConversationIds(prev => {
      const next = new Set(prev);
      next.delete(currentConversationId);
      return next;
    });
    // Mark last assistant message as cancelled
    setCurrentConversation((prev) => {
      if (!prev) return prev;
      const messages = [...prev.messages];
      const lastMsg = { ...messages[messages.length - 1] };
      if (lastMsg.role === 'assistant') {
        lastMsg.loading = { stage0: false, stage1: false, stage2: false, stage3: false };
        lastMsg.cancelled = true;
        messages[messages.length - 1] = lastMsg;
      }
      return { ...prev, messages };
    });
  };

  const handleClarificationSubmit = async (answers) => {
    if (!currentConversationId) return;

    const targetId = currentConversationId;
    setLoadingConversationIds(prev => new Set(prev).add(targetId));

    // Clear clarification questions, show loading
    setCurrentConversation((prev) => {
      if (!prev || prev.id !== targetId) return prev;
      const messages = [...prev.messages];
      const lastMsg = { ...messages[messages.length - 1] };
      lastMsg.clarificationQuestions = null;
      lastMsg.loading = { stage0: false, stage1: false, stage2: false, stage3: false };
      messages[messages.length - 1] = lastMsg;
      return { ...prev, messages };
    });

    const removeLoading = () => {
      setLoadingConversationIds(prev => {
        const next = new Set(prev);
        next.delete(targetId);
        return next;
      });
    };

    try {
      await api.sendClarificationStream(currentConversationId, answers, (eventType, event) => {
        handleCouncilEvent(targetId, eventType, event);
      });
    } catch (error) {
      console.error('Failed to send clarification:', error);
      removeLoading();
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
        loadingConversationIds={loadingConversationIds}
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
        isLoading={isCurrentLoading}
        onClarificationSubmit={handleClarificationSubmit}
        onCancel={handleCancelStream}
        queryRewriteEnabled={queryRewriteEnabled}
        onToggleQueryRewrite={() => setQueryRewriteEnabled(prev => !prev)}
      />
    </div>
  );
}

export default App;
