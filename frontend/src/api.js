/**
 * API client for the LLM Council backend.
 */

const API_BASE = 'http://localhost:8001';

/**
 * Read an SSE stream, buffering across chunk boundaries.
 * Calls onEvent(eventType, eventData) for each parsed event.
 */
async function readSSEStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n');
    buffer = parts.pop(); // keep incomplete trailing line

    for (const line of parts) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6));
          onEvent(event.type, event);
        } catch (e) {
          console.error('Failed to parse SSE event:', e);
        }
      }
    }
  }
}

export const api = {
  /**
   * List all conversations.
   */
  async listConversations({ includeArchived = false } = {}) {
    const params = new URLSearchParams();
    if (includeArchived) {
      params.set('include_archived', 'true');
    }
    const query = params.toString();
    const response = await fetch(
      `${API_BASE}/api/conversations${query ? `?${query}` : ''}`
    );
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Update conversation metadata.
   */
  async updateConversation(conversationId, updates) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(updates),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to update conversation');
    }
    return response.json();
  },

  /**
   * Delete a conversation.
   */
  async deleteConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'DELETE',
      }
    );
    if (!response.ok) {
      throw new Error('Failed to delete conversation');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent, { signal, skipRewrite = false } = {}) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content, skip_rewrite: skipRewrite }),
        signal,
      }
    );

    if (!response.ok) {
      throw new Error('Failed to send message');
    }

    await readSSEStream(response, onEvent);
  },

  /**
   * Subscribe to a running council task's event stream (for reconnection).
   */
  async subscribeToTask(conversationId, onEvent, { signal } = {}) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/subscribe`,
      { signal }
    );

    if (!response.ok) {
      throw new Error('Failed to subscribe to task');
    }

    await readSSEStream(response, onEvent);
  },

  /**
   * Cancel a running council task.
   */
  async cancelTask(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/cancel`,
      { method: 'POST' }
    );
    return response.ok;
  },

  /**
   * Check if a council task is running for a conversation.
   */
  async getTaskStatus(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/task-status`
    );
    if (!response.ok) throw new Error('Failed to get task status');
    return response.json();
  },

  async sendClarificationStream(conversationId, answers, onEvent) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/clarify/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ answers }),
      }
    );

    if (!response.ok) {
      throw new Error('Failed to send clarification');
    }

    await readSSEStream(response, onEvent);
  },
};
