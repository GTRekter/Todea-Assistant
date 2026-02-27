import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
    faArrowUp,
    faChevronDown,
    faChevronUp,
    faPlus,
    faTrash,
    faPen,
} from '@fortawesome/free-solid-svg-icons';
import './chat.css';
import {
    streamChatRequest,
    getModels,
    listConversations,
    createConversation,
    fetchConversation,
    renameConversation,
    deleteConversation,
} from '../services/agentHubApi';

function ThinkingBlock({ steps }) {
    const [expanded, setExpanded] = useState(false);
    const count = steps.length;
    return (
        <div className="thinking-block mb-2">
            <button
                type="button"
                className="thinking-header"
                onClick={() => setExpanded((prev) => !prev)}
                aria-expanded={expanded}
            >
                <FontAwesomeIcon icon={expanded ? faChevronUp : faChevronDown} className="thinking-chevron" />
                <span>Thinking · {count} step{count !== 1 ? 's' : ''}</span>
            </button>
            {expanded && (
                <div className="thinking-content d-flex flex-column gap-1">
                    {steps.map((step, i) => {
                        if (step.type === 'thinking') return (
                            <p key={i} className="mb-0 small fst-italic text-secondary">{step.content}</p>
                        );
                        if (step.type === 'tool_call') return (
                            <div key={i} className="d-flex align-items-center gap-1">
                                <span className="badge bg-secondary">tool</span>
                                <code className="small">{step.name}</code>
                            </div>
                        );
                        if (step.type === 'tool_result') return (
                            <pre key={i} className="mb-0 small p-2 rounded bg-black text-light" style={{ maxHeight: '10rem', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>{step.content}</pre>
                        );
                        return null;
                    })}
                </div>
            )}
        </div>
    );
}

const initialMessages = [
    {
        id: 'assistant-intro',
        role: 'assistant',
        content: "Hi, I'm your workspace assistant. Ask me about hot topics, channel activity, or workspace settings and I'll help you manage them.",
    },
];

const PROVIDER_ID = 'google';

export default function Chat() {
    const [models, setModels] = useState([]);
    const [selectedModel, setSelectedModel] = useState(null);
    const [isModelMenuOpen, setIsModelMenuOpen] = useState(false);
    const [inputValue, setInputValue] = useState('');
    const [isSending, setIsSending] = useState(false);

    const [conversations, setConversations] = useState([]);
    const [activeConversationId, setActiveConversationId] = useState(null);
    const [messagesByConversation, setMessagesByConversation] = useState({});
    const [isSidebarLoading, setIsSidebarLoading] = useState(true);

    const scrollAnchorRef = useRef(null);
    const modelDropdownRef = useRef(null);

    const selectedProvider = PROVIDER_ID;

    const activeConversation = useMemo(
        () => conversations.find((c) => c.id === activeConversationId) || null,
        [conversations, activeConversationId],
    );

    const activeMessages = useMemo(
        () => messagesByConversation[activeConversationId] || [],
        [messagesByConversation, activeConversationId],
    );

    const displayMessages = activeMessages.length ? activeMessages : initialMessages;

    // ---------------------------------------------------------------------
    // Data loaders
    // ---------------------------------------------------------------------

    const hydrateConversation = useCallback(async (conversationId) => {
        if (!conversationId) return;
        try {
            const detail = await fetchConversation(conversationId);
            setMessagesByConversation((prev) => ({
                ...prev,
                [conversationId]: detail.messages || [],
            }));
            setConversations((prev) => {
                const others = prev.filter((c) => c.id !== conversationId);
                return [detail, ...others];
            });
            if (detail.model) {
                setSelectedModel(detail.model);
            }
        } catch (err) {
            console.error('Failed to hydrate conversation', err);
        }
    }, []);

    const loadInitialData = useCallback(async () => {
        setIsSidebarLoading(true);
        try {
            const [modelData, conversationData] = await Promise.all([
                getModels(),
                listConversations(),
            ]);

            const nextModel = modelData?.default || modelData?.models?.[0] || null;
            setModels(modelData?.models || []);
            setSelectedModel(nextModel);

            if (!conversationData.length) {
                const created = await createConversation({ model: nextModel });
                setConversations([created]);
                setActiveConversationId(created.id);
                setMessagesByConversation({ [created.id]: [] });
            } else {
                setConversations(conversationData);
                const firstId = conversationData[0]?.id;
                setActiveConversationId(firstId);
                await hydrateConversation(firstId);
            }
        } catch (err) {
            console.error('Failed to load initial chat data', err);
        } finally {
            setIsSidebarLoading(false);
        }
    }, [hydrateConversation]);

    useEffect(() => {
        loadInitialData();
    }, [loadInitialData]);

    // Close model dropdown on outside click
    useEffect(() => {
        if (!isModelMenuOpen) return;
        const handleClickOutside = (event) => {
            if (modelDropdownRef.current && !modelDropdownRef.current.contains(event.target)) {
                setIsModelMenuOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isModelMenuOpen]);

    // Scroll to bottom when messages change
    useEffect(() => {
        if (scrollAnchorRef.current) {
            scrollAnchorRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [activeConversationId, activeMessages.length]);

    // ---------------------------------------------------------------------
    // Conversation helpers
    // ---------------------------------------------------------------------

    const createAndActivateConversation = useCallback(async () => {
        const conversation = await createConversation({ model: selectedModel });
        setConversations((prev) => [conversation, ...prev]);
        setMessagesByConversation((prev) => ({
            ...prev,
            [conversation.id]: [],
        }));
        setActiveConversationId(conversation.id);
        setInputValue('');
        return conversation;
    }, [selectedModel]);

    const handleSelectConversation = async (conversationId) => {
        setActiveConversationId(conversationId);
        if (!messagesByConversation[conversationId]) {
            await hydrateConversation(conversationId);
        }
    };

    const handleDeleteConversation = async (conversationId, event) => {
        if (event?.stopPropagation) event.stopPropagation();
        if (!conversationId) return;
        try {
            await deleteConversation(conversationId);
            setConversations((prev) => prev.filter((c) => c.id !== conversationId));
            setMessagesByConversation((prev) => {
                const next = { ...prev };
                delete next[conversationId];
                return next;
            });
            if (conversationId === activeConversationId) {
                const fallback = conversations.find((c) => c.id !== conversationId);
                if (fallback) {
                    setActiveConversationId(fallback.id);
                    if (!messagesByConversation[fallback.id]) {
                        await hydrateConversation(fallback.id);
                    }
                } else {
                    const created = await createAndActivateConversation();
                    await hydrateConversation(created.id);
                }
            }
        } catch (err) {
            console.error('Failed to delete conversation', err);
        }
    };

    const handleRenameConversation = async (conversationId, event) => {
        if (event?.stopPropagation) event.stopPropagation();
        const current = conversations.find((c) => c.id === conversationId);
        const nextTitle = window.prompt('Name this conversation', current?.title || 'Conversation');
        if (!nextTitle || !nextTitle.trim()) return;
        try {
            const updated = await renameConversation({ conversationId, title: nextTitle.trim() });
            setConversations((prev) => {
                const others = prev.filter((c) => c.id !== conversationId);
                return [updated, ...others];
            });
        } catch (err) {
            console.error('Failed to rename conversation', err);
        }
    };

    // ---------------------------------------------------------------------
    // Chat handling
    // ---------------------------------------------------------------------

    const executeChat = useCallback(
        async (userContent, conversationId) => {
            const ts = Date.now();
            const placeholderId = `assistant-${ts}`;
            const userMessage = {
                id: `user-${ts}`,
                role: 'user',
                content: userContent,
                timestamp: ts,
            };
            const placeholder = {
                id: placeholderId,
                role: 'assistant',
                content: `Thinking with ${selectedModel}…`,
                placeholder: true,
                timestamp: ts,
            };

            setMessagesByConversation((prev) => {
                const existing = prev[conversationId] || [];
                return {
                    ...prev,
                    [conversationId]: [...existing, userMessage, placeholder],
                };
            });

            try {
                const steps = [];
                await streamChatRequest({
                    message: userContent,
                    provider: selectedProvider,
                    sessionId: conversationId,
                    model: selectedModel,
                    onEvent: (event) => {
                        if (event.type === 'done') {
                            setMessagesByConversation((prev) => {
                                const updated = (prev[conversationId] || []).map((m) =>
                                    m.id === placeholderId
                                        ? { ...m, content: event.content || 'The assistant did not return any text.', placeholder: false, steps: [...steps] }
                                        : m
                                );
                                return { ...prev, [conversationId]: updated };
                            });
                        } else if (event.type === 'error') {
                            setMessagesByConversation((prev) => {
                                const updated = (prev[conversationId] || []).map((m) =>
                                    m.id === placeholderId
                                        ? { ...m, content: `Error: ${event.content}`, placeholder: false, steps: [...steps] }
                                        : m
                                );
                                return { ...prev, [conversationId]: updated };
                            });
                        } else {
                            steps.push(event);
                            setMessagesByConversation((prev) => {
                                const updated = (prev[conversationId] || []).map((m) =>
                                    m.id === placeholderId ? { ...m, steps: [...steps] } : m
                                );
                                return { ...prev, [conversationId]: updated };
                            });
                        }
                    },
                });
            } catch (error) {
                console.error('Failed to process chat request', error);
                const message = error instanceof Error ? error.message : String(error);
                setMessagesByConversation((prev) => {
                    const updated = (prev[conversationId] || []).map((m) =>
                        m.id === placeholderId
                            ? { ...m, content: `Error: ${message}`, placeholder: false }
                            : m
                    );
                    return { ...prev, [conversationId]: updated };
                });
            } finally {
                setIsSending(false);
                setConversations((prev) => {
                    const now = Date.now() / 1000;
                    const updated = prev.find((c) => c.id === conversationId);
                    const updatedItem = updated
                        ? { ...updated, updated_at: now, message_count: (updated.message_count || 0) + 2 }
                        : {
                              id: conversationId,
                              title: 'Conversation',
                              model: selectedModel,
                              created_at: now,
                              updated_at: now,
                              message_count: 2,
                          };
                    const others = prev.filter((c) => c.id !== conversationId);
                    return [updatedItem, ...others];
                });
            }
        },
        [selectedModel, selectedProvider],
    );

    const handleSubmit = async (event) => {
        event.preventDefault();
        const trimmed = inputValue.trim();
        if (!trimmed || isSending) return;
        setIsSending(true);
        setInputValue('');
        let targetConversationId = activeConversationId;
        if (!targetConversationId) {
            const created = await createAndActivateConversation();
            targetConversationId = created.id;
        }
        await executeChat(trimmed, targetConversationId);
    };

    const handleKeyDown = (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            handleSubmit(event);
        }
    };

    const handleNewConversationClick = async () => {
        try {
            await createAndActivateConversation();
        } catch (err) {
            console.error('Failed to create conversation', err);
        }
    };

    const isReady = models.length > 0 && !!selectedModel && !!activeConversationId;

    const handleSelectModel = (model) => {
        setSelectedModel(model);
        setConversations((prev) =>
            prev.map((c) => (c.id === activeConversationId ? { ...c, model } : c))
        );
        setIsModelMenuOpen(false);
    };

    // ---------------------------------------------------------------------
    // Rendering helpers
    // ---------------------------------------------------------------------

    const renderConversation = (conversation) => {
        const isActive = conversation.id === activeConversationId;
        return (
            <button
                key={conversation.id}
                type="button"
                className={`conversation-item ${isActive ? 'active' : ''}`}
                onClick={() => handleSelectConversation(conversation.id)}
            >
                <div className="d-flex justify-content-between align-items-start gap-2">
                    <div className="flex-grow-1 text-start">
                        <div className="conversation-title">{conversation.title}</div>
                        <div className="conversation-meta text-muted small">
                            {conversation.model} · {conversation.message_count || 0} message{(conversation.message_count || 0) === 1 ? '' : 's'}
                        </div>
                    </div>
                    <div className="conversation-actions d-flex gap-1">
                        <button
                            type="button"
                            className="icon-btn"
                            title="Rename"
                            onClick={(event) => handleRenameConversation(conversation.id, event)}
                        >
                            <FontAwesomeIcon icon={faPen} />
                        </button>
                        <button
                            type="button"
                            className="icon-btn"
                            title="Delete"
                            onClick={(event) => handleDeleteConversation(conversation.id, event)}
                        >
                            <FontAwesomeIcon icon={faTrash} />
                        </button>
                    </div>
                </div>
            </button>
        );
    };

    return (
        <div className="chat-layout row g-4">
            <div className="col-12 col-lg-4">
                <div className="panel-card conversation-sidebar">
                    <div className="d-flex justify-content-between align-items-center mb-3">
                        <div>
                            <p className="eyebrow text-uppercase mb-1">Conversations</p>
                            <h5 className="mb-0">Threads</h5>
                        </div>
                        <button
                            type="button"
                            className="btn btn-primary btn-sm d-inline-flex align-items-center gap-2"
                            onClick={handleNewConversationClick}
                            disabled={isSending || isSidebarLoading}
                        >
                            <FontAwesomeIcon icon={faPlus} />
                            New
                        </button>
                    </div>
                    <div className="conversation-list">
                        {isSidebarLoading && (
                            <div className="text-muted small py-2">Loading conversations…</div>
                        )}
                        {!isSidebarLoading && !conversations.length && (
                            <div className="text-muted small py-2">No conversations yet.</div>
                        )}
                        {!isSidebarLoading && conversations.map(renderConversation)}
                    </div>
                </div>
            </div>

            <div className="col-12 col-lg-8">
                <div className="panel-card bg-dark text-light d-flex flex-column chat-shell">
                    <div className="d-flex justify-content-between align-items-center mb-3">
                        <div>
                            <p className="eyebrow text-uppercase mb-1">Active chat</p>
                            <h5 className="mb-0">{activeConversation?.title || 'New conversation'}</h5>
                            <small className="text-muted">Model: {selectedModel || '—'}</small>
                        </div>
                        <div
                            ref={modelDropdownRef}
                            className={`dropdown ${isModelMenuOpen ? 'show' : ''}`}
                        >
                            <button
                                type="button"
                                className="btn btn-outline-light rounded-circle d-flex align-items-center justify-content-center chat-btn"
                                onClick={() => setIsModelMenuOpen((prev) => !prev)}
                                disabled={!isReady}
                                aria-haspopup="true"
                                aria-expanded={isModelMenuOpen}
                                aria-label="Select model"
                            >
                                <FontAwesomeIcon icon={faChevronDown} />
                            </button>
                            <div className={`dropdown-menu dropdown-menu-end dropdown-menu-dark ${isModelMenuOpen ? 'show' : ''}`}>
                                {(models ?? []).map((model) => (
                                    <button
                                        key={model}
                                        type="button"
                                        className={`dropdown-item${selectedModel === model ? ' active' : ''}`}
                                        onClick={() => handleSelectModel(model)}
                                    >
                                        {model}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="card-body d-flex flex-column gap-3 overflow-auto chat-body">
                        {displayMessages.map((message) => (
                            <div
                                key={message.id}
                                className={`d-flex ${message.role === 'user' ? 'justify-content-end' : 'justify-content-start'}`}
                            >
                                <div className={`px-3 py-2 chat-message-bubble ${message.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}>
                                    {message.steps?.length > 0 && (
                                        <ThinkingBlock steps={message.steps} />
                                    )}
                                    {message.placeholder && !message.steps?.length && (
                                        <span className="text-secondary fst-italic small">Thinking with {selectedModel}…</span>
                                    )}
                                    {message.content && (
                                        <div>{message.content}</div>
                                    )}
                                </div>
                            </div>
                        ))}
                        <div ref={scrollAnchorRef} />
                    </div>

                    <form className="p-3 chat-input-area" onSubmit={handleSubmit}>
                        <div className="mb-3">
                            <textarea
                                rows={1}
                                className="form-control border-0 bg-transparent text-light chat-input"
                                placeholder="Message the workspace assistant…"
                                value={inputValue}
                                onChange={(event) => setInputValue(event.target.value)}
                                onKeyDown={handleKeyDown}
                                disabled={!isReady || isSending}
                            />
                        </div>
                        <div className="d-flex flex-wrap justify-content-end align-items-center gap-2">
                            <button
                                type="submit"
                                className="btn btn-light rounded-circle d-flex align-items-center justify-content-center chat-btn"
                                disabled={!isReady || isSending || !inputValue.trim()}
                                aria-label="Send message"
                            >
                                <FontAwesomeIcon icon={faArrowUp} />
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    );
}
