const AGENT_HUB_URL =
    process.env.REACT_APP_AGENT_HUB_URL || 'http://localhost:3100/chat';

// Derive the base URL by stripping the trailing /chat path if present.
const AGENT_HUB_BASE_URL = AGENT_HUB_URL.replace(/\/chat$/, '');
const CONVERSATIONS_URL = `${AGENT_HUB_BASE_URL}/conversations`;

export async function getModels() {
    const response = await fetch(`${AGENT_HUB_BASE_URL}/models`);
    if (!response.ok) throw new Error(`Failed to load models (${response.status})`);
    return response.json();
}

export async function sendChatRequest({ message, provider, sessionId, model }) {
    const trimmed = (message || '').trim();
    if (!trimmed) {
        throw new Error('A message is required.');
    }
    const payload = {
        message: trimmed,
        provider: provider || 'google',
        session_id: sessionId || undefined,
        model: model || undefined,
    };

    const response = await fetch(`${AGENT_HUB_BASE_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || `Agent Hub error (${response.status})`);
    }
    const data = await response.json();
    return data?.content || '';
}

export async function streamChatRequest({ message, provider, sessionId, model, onEvent }) {
    const trimmed = (message || '').trim();
    if (!trimmed) throw new Error('A message is required.');

    const payload = {
        message: trimmed,
        provider: provider || 'google',
        session_id: sessionId || undefined,
        model: model || undefined,
    };

    const response = await fetch(`${AGENT_HUB_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || `Agent Hub error (${response.status})`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep any incomplete line
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    onEvent(JSON.parse(line.slice(6)));
                } catch (_) {
                    // ignore malformed lines
                }
            }
        }
    }
}

export async function saveSettings({ googleApiKey }) {
    const response = await fetch(`${AGENT_HUB_BASE_URL}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ google_api_key: googleApiKey })
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || `Settings error (${response.status})`);
    }
    return response.json();
}

export async function getSettingsStatus() {
    const response = await fetch(`${AGENT_HUB_BASE_URL}/settings/status`);
    if (!response.ok) {
        throw new Error(`Status check failed (${response.status})`);
    }
    return response.json();
}

export async function getClusterSettings() {
    const response = await fetch(`${AGENT_HUB_BASE_URL}/settings/cluster`);
    if (!response.ok) {
        throw new Error(`Failed to load cluster settings (${response.status})`);
    }
    return response.json();
}

export async function saveClusterSettings({ kubeServer }) {
    const response = await fetch(`${AGENT_HUB_BASE_URL}/settings/cluster`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kube_server: kubeServer }),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || `Cluster settings error (${response.status})`);
    }
    return response.json();
}

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------

export async function listConversations() {
    const response = await fetch(CONVERSATIONS_URL);
    if (!response.ok) {
        throw new Error(`Failed to load conversations (${response.status})`);
    }
    const data = await response.json();
    return data?.conversations || [];
}

export async function createConversation({ title, model }) {
    const response = await fetch(CONVERSATIONS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            title: title || undefined,
            model: model || undefined,
        }),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || `Failed to create conversation (${response.status})`);
    }
    return response.json();
}

export async function fetchConversation(conversationId) {
    if (!conversationId) throw new Error('conversationId is required');
    const response = await fetch(`${CONVERSATIONS_URL}/${conversationId}`);
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || `Failed to load conversation (${response.status})`);
    }
    return response.json();
}

export async function renameConversation({ conversationId, title }) {
    if (!conversationId) throw new Error('conversationId is required');
    const response = await fetch(`${CONVERSATIONS_URL}/${conversationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || `Failed to rename conversation (${response.status})`);
    }
    return response.json();
}

export async function deleteConversation(conversationId) {
    if (!conversationId) throw new Error('conversationId is required');
    const response = await fetch(`${CONVERSATIONS_URL}/${conversationId}`, {
        method: 'DELETE',
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || `Failed to delete conversation (${response.status})`);
    }
    return response.json();
}
