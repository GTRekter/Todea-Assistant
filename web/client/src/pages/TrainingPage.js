import { useState, useEffect, useRef, useCallback } from 'react';
import {
    getTrainingSettings,
    saveGithubToken,
    startScrape,
    startTrain,
    getJobs,
    cancelJob,
    streamLogs,
} from '../services/trainingApi';
import './trainingPage.css';

const POLL_INTERVAL_MS = 5000;
const AVAILABLE_MODELS_FALLBACK = ['qwen2.5:7b-instruct', 'llama3.1:8b', 'llama3.2:3b', 'mistral:7b'];

const today = () => {
    const d = new Date();
    return `adapter-${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const phaseChip = (phase) => {
    const map = {
        Running: 'chip-running',
        Succeeded: 'chip-success',
        Failed: 'chip-error',
        Pending: 'chip-pending',
    };
    return `status-chip ${map[phase] || ''}`;
};

const phaseIcon = (phase) => {
    if (phase === 'Running') return '●';
    if (phase === 'Succeeded') return '✓';
    if (phase === 'Failed') return '✗';
    return '○';
};

const TrainingPage = () => {
    // Remote settings
    const [settings, setSettings] = useState(null);
    const [loadError, setLoadError] = useState(null);

    // GitHub token
    const [githubToken, setGithubToken] = useState('');
    const [showToken, setShowToken] = useState(false);
    const [tokenStatus, setTokenStatus] = useState(null); // null | 'saving' | 'saved' | 'error'
    const [tokenMsg, setTokenMsg] = useState('');

    // Data sources
    const [selectedRepos, setSelectedRepos] = useState(new Set());
    const [selectedWebsites, setSelectedWebsites] = useState(new Set());
    const [customRepos, setCustomRepos] = useState([]);
    const [customRepoInput, setCustomRepoInput] = useState('');

    // Model config
    const [selectedModel, setSelectedModel] = useState('qwen2.5:7b-instruct');
    const [adapterName, setAdapterName] = useState(today());
    const [gpuNodePool, setGpuNodePool] = useState('');

    // Job actions
    const [scrapeError, setScrapeError] = useState(null);
    const [trainError, setTrainError] = useState(null);
    const [scrapeStarting, setScrapeStarting] = useState(false);
    const [trainStarting, setTrainStarting] = useState(false);

    // Jobs list
    const [jobs, setJobs] = useState([]);

    // Log viewer
    const [logJobName, setLogJobName] = useState(null);
    const [logLines, setLogLines] = useState([]);
    const [logOpen, setLogOpen] = useState(false);
    const logEndRef = useRef(null);
    const esRef = useRef(null);
    const pollRef = useRef(null);

    // ── Load settings once ────────────────────────────────────────────────────
    useEffect(() => {
        getTrainingSettings()
            .then((s) => {
                setSettings(s);
                const defaultRepos = new Set(s.repos.filter((r) => r.default).map((r) => r.id));
                const defaultSites = new Set(s.websites.filter((w) => w.default).map((w) => w.id));
                setSelectedRepos(defaultRepos);
                setSelectedWebsites(defaultSites);
            })
            .catch((err) => setLoadError(err.message));
    }, []);

    // ── Normalise model options ───────────────────────────────────────────────
    const modelOptions = (settings?.models || AVAILABLE_MODELS_FALLBACK)
        .map((m) => {
            if (typeof m === 'string') return { value: m, label: m };
            if (!m) return null;
            const value = m.value || m.id || m.name || m.label;
            const label = m.label || m.name || m.value || m.id || String(value || '');
            return value ? { value, label } : null;
        })
        .filter(Boolean);

    useEffect(() => {
        if (modelOptions.length === 0) return;
        const hasSelected = modelOptions.some((m) => m.value === selectedModel);
        if (!hasSelected) setSelectedModel(modelOptions[0].value);
    }, [settings]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── Job polling ───────────────────────────────────────────────────────────
    const refreshJobs = useCallback(() => {
        getJobs()
            .then((r) => setJobs(r.jobs))
            .catch(() => {});
    }, []);

    useEffect(() => {
        refreshJobs();
        pollRef.current = setInterval(refreshJobs, POLL_INTERVAL_MS);
        return () => clearInterval(pollRef.current);
    }, [refreshJobs]);

    // ── Auto-scroll logs ──────────────────────────────────────────────────────
    useEffect(() => {
        logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logLines]);

    // ── Log streaming ─────────────────────────────────────────────────────────
    const openLogs = (jobName) => {
        if (esRef.current) esRef.current.close();
        setLogJobName(jobName);
        setLogLines([]);
        setLogOpen(true);
        const es = streamLogs(
            jobName,
            (line) => setLogLines((prev) => [...prev, line]),
        );
        esRef.current = es;
    };

    const closeLogs = () => {
        if (esRef.current) { esRef.current.close(); esRef.current = null; }
        setLogOpen(false);
        setLogLines([]);
        setLogJobName(null);
    };

    useEffect(() => () => { if (esRef.current) esRef.current.close(); }, []);

    // ── Actions ───────────────────────────────────────────────────────────────
    const handleSaveToken = async (e) => {
        e?.preventDefault();
        if (!githubToken.trim()) return;
        setTokenStatus('saving');
        setTokenMsg('');
        try {
            await saveGithubToken(githubToken.trim());
            setTokenStatus('saved');
            setTokenMsg('Token saved to Kubernetes secret todea-github-token.');
            setGithubToken('');
            setSettings((prev) => prev ? { ...prev, github_token_exists: true } : prev);
        } catch (err) {
            setTokenStatus('error');
            setTokenMsg(err.message || 'Failed to save token.');
        }
    };

    const handleScrape = async () => {
        setScrapeError(null);
        setScrapeStarting(true);
        try {
            const { job_name } = await startScrape(
                [...selectedRepos],
                [...selectedWebsites],
            );
            refreshJobs();
            openLogs(job_name);
        } catch (err) {
            setScrapeError(err.message);
        } finally {
            setScrapeStarting(false);
        }
    };

    const handleTrain = async () => {
        setTrainError(null);
        setTrainStarting(true);
        try {
            const { job_name } = await startTrain(selectedModel, adapterName, gpuNodePool);
            refreshJobs();
            openLogs(job_name);
        } catch (err) {
            setTrainError(err.message);
        } finally {
            setTrainStarting(false);
        }
    };

    const handleCancel = async (jobName) => {
        try {
            await cancelJob(jobName);
            refreshJobs();
            if (logJobName === jobName) closeLogs();
        } catch (err) {
            alert(`Failed to cancel: ${err.message}`);
        }
    };

    const handleDelete = async (jobName) => {
        try {
            await cancelJob(jobName);
            refreshJobs();
            if (logJobName === jobName) closeLogs();
        } catch (err) {
            alert(`Failed to delete: ${err.message}`);
        }
    };

    // ── Derived ───────────────────────────────────────────────────────────────
    const scraperJob = jobs.find((j) => j.type === 'scraper' && j.phase === 'Running');
    const trainerJob = jobs.find((j) => j.type === 'trainer' && j.phase === 'Running');
    const recentJobs = jobs.slice(0, 8);

    const toggleRepo = (id) =>
        setSelectedRepos((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });

    const addCustomRepo = () => {
        const val = customRepoInput.trim();
        if (!val || !/^[^/]+\/[^/]+$/.test(val)) return;
        if (customRepos.includes(val) || (settings?.repos || []).some((r) => r.id === val)) return;
        setCustomRepos((prev) => [...prev, val]);
        setSelectedRepos((prev) => new Set([...prev, val]));
        setCustomRepoInput('');
    };

    const removeCustomRepo = (id) => {
        setCustomRepos((prev) => prev.filter((r) => r !== id));
        setSelectedRepos((prev) => { const next = new Set(prev); next.delete(id); return next; });
    };

    const toggleWebsite = (id) =>
        setSelectedWebsites((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });

    // ── Render ────────────────────────────────────────────────────────────────
    return (
        <div className="container full-height-container settings training-page">
            <div className="panel-card text-white">

                {/* Header */}
                <div className="row align-items-lg-center justify-content-between mb-2">
                    <div className="col-lg">
                        <p className="eyebrow text-uppercase">ML Pipeline</p>
                        <h2>Training</h2>
                        <p className="text-muted">
                            Scrape data sources, fine-tune a model on Kubernetes, and deploy the adapter.
                        </p>
                    </div>
                </div>

                {loadError && (
                    <div className="alert alert-warning mt-2">
                        Could not reach training hub: {loadError}
                    </div>
                )}

                {/* ── 1. Data Sources ─────────────────────────────────────── */}
                <div className="control-group mt-4">
                    <p className="text-uppercase text-muted small mb-1">1. Data Sources</p>
                    <p className="text-muted mb-3">
                        Configure what to scrape. GitHub token is stored as a Kubernetes secret.
                    </p>

                    {/* GitHub token */}
                    <div className="row g-4 mb-4">
                        <div className="col-12 col-lg-5">
                            <label className="form-label">GitHub token</label>
                            <div className="input-group stacked-input">
                                <input
                                    type={showToken ? 'text' : 'password'}
                                    className="form-control"
                                    placeholder={settings?.github_token_exists ? 'Token already saved — enter to replace' : 'ghp_…'}
                                    value={githubToken}
                                    onChange={(e) => setGithubToken(e.target.value)}
                                    autoComplete="off"
                                />
                                <button
                                    type="button"
                                    className="btn btn-outline-secondary"
                                    onClick={() => setShowToken((v) => !v)}
                                    tabIndex={-1}
                                >
                                    {showToken ? 'Hide' : 'Show'}
                                </button>
                            </div>
                            <button
                                className="btn btn-primary w-100 mt-2"
                                onClick={handleSaveToken}
                                disabled={tokenStatus === 'saving' || !githubToken.trim()}
                            >
                                {tokenStatus === 'saving' ? 'Saving…' : 'Save token'}
                            </button>
                            {tokenMsg && (
                                <div className="mt-2">
                                    <span className={`status-chip ${tokenStatus === 'saved' ? 'configured' : 'error'}`}>
                                        {tokenStatus === 'saved' ? '✓' : '⚠'} {tokenMsg}
                                    </span>
                                </div>
                            )}
                            {settings?.github_token_exists && tokenStatus !== 'saved' && (
                                <div className="mt-2">
                                    <span className="status-chip configured">✓ Token configured</span>
                                </div>
                            )}
                        </div>

                        {/* Repos */}
                        <div className="col-12 col-lg-4">
                            <label className="form-label">GitHub repositories</label>
                            <div className="source-list">
                                {(settings?.repos || []).map((r) => (
                                    <label key={r.id} className="source-item">
                                        <input
                                            type="checkbox"
                                            checked={selectedRepos.has(r.id)}
                                            onChange={() => toggleRepo(r.id)}
                                        />
                                        <span>{r.label}</span>
                                    </label>
                                ))}
                                {customRepos.map((id) => (
                                    <div key={id} className="source-item custom-repo-item">
                                        <input
                                            type="checkbox"
                                            checked={selectedRepos.has(id)}
                                            onChange={() => toggleRepo(id)}
                                        />
                                        <span className="flex-grow-1">{id}</span>
                                        <button
                                            type="button"
                                            className="custom-repo-remove"
                                            onClick={() => removeCustomRepo(id)}
                                            title="Remove"
                                        >✕</button>
                                    </div>
                                ))}
                            </div>
                            <div className="add-repo-row mt-2">
                                <input
                                    type="text"
                                    className="form-control form-control-sm"
                                    placeholder="owner/repo"
                                    value={customRepoInput}
                                    onChange={(e) => setCustomRepoInput(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && addCustomRepo()}
                                />
                                <button
                                    type="button"
                                    className="btn btn-outline-secondary btn-sm"
                                    onClick={addCustomRepo}
                                    disabled={!/^[^/]+\/[^/]+$/.test(customRepoInput.trim())}
                                >Add</button>
                            </div>
                        </div>

                        {/* Websites */}
                        <div className="col-12 col-lg-3">
                            <label className="form-label">Websites</label>
                            <div className="source-list">
                                {(settings?.websites || []).map((w) => (
                                    <label key={w.id} className="source-item">
                                        <input
                                            type="checkbox"
                                            checked={selectedWebsites.has(w.id)}
                                            onChange={() => toggleWebsite(w.id)}
                                        />
                                        <span>{w.label}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="d-flex align-items-center gap-3 flex-wrap">
                        <button
                            className="btn btn-primary"
                            onClick={handleScrape}
                            disabled={
                                scrapeStarting ||
                                !!scraperJob ||
                                (selectedRepos.size === 0 && selectedWebsites.size === 0)
                            }
                        >
                            {scrapeStarting ? 'Starting…' : scraperJob ? 'Scraper running…' : 'Start scraping'}
                        </button>
                        {scraperJob && (
                            <button
                                className="btn btn-outline-danger btn-sm"
                                onClick={() => handleCancel(scraperJob.name)}
                            >
                                Cancel
                            </button>
                        )}
                        {scraperJob && (
                            <button
                                className="btn btn-outline-primary btn-sm"
                                onClick={() => openLogs(scraperJob.name)}
                            >
                                View logs
                            </button>
                        )}
                        {scrapeError && <span className="text-danger small">{scrapeError}</span>}
                    </div>
                </div>

                {/* ── 2. Model Configuration ───────────────────────────────── */}
                <div className="control-group mt-4">
                    <p className="text-uppercase text-muted small mb-1">2. Model Configuration</p>
                    <p className="text-muted mb-3">
                        Select the base model and GPU node pool, then start training.
                    </p>

                    <div className="row g-3 mb-4">
                        <div className="col-12 col-md-4">
                            <label className="form-label">Base model</label>
                            <select
                                className="form-select"
                                value={selectedModel}
                                onChange={(e) => setSelectedModel(e.target.value)}
                            >
                                {modelOptions.map((m) => (
                                    <option key={m.value} value={m.value}>{m.label}</option>
                                ))}
                            </select>
                        </div>
                        <div className="col-12 col-md-4">
                            <label className="form-label">Adapter name</label>
                            <input
                                type="text"
                                className="form-control"
                                placeholder={today()}
                                value={adapterName}
                                onChange={(e) => setAdapterName(e.target.value)}
                            />
                        </div>
                        <div className="col-12 col-md-4">
                            <label className="form-label">GPU node pool <span className="text-muted">(optional)</span></label>
                            <input
                                type="text"
                                className="form-control"
                                placeholder="gpupool"
                                value={gpuNodePool}
                                onChange={(e) => setGpuNodePool(e.target.value)}
                            />
                        </div>
                    </div>

                    <div className="d-flex align-items-center gap-3 flex-wrap">
                        <button
                            className="btn btn-primary"
                            onClick={handleTrain}
                            disabled={trainStarting || !!trainerJob}
                        >
                            {trainStarting ? 'Starting…' : trainerJob ? 'Training running…' : 'Start training'}
                        </button>
                        {trainerJob && (
                            <button
                                className="btn btn-outline-danger btn-sm"
                                onClick={() => handleCancel(trainerJob.name)}
                            >
                                Cancel
                            </button>
                        )}
                        {trainerJob && (
                            <button
                                className="btn btn-outline-primary btn-sm"
                                onClick={() => openLogs(trainerJob.name)}
                            >
                                View logs
                            </button>
                        )}
                        {trainError && <span className="text-danger small">{trainError}</span>}
                    </div>
                </div>

                {/* ── 3. Status ────────────────────────────────────────────── */}
                <div className="control-group mt-4">
                    <p className="text-uppercase text-muted small mb-1">3. Job Status</p>

                    {recentJobs.length === 0 ? (
                        <p className="text-muted mb-0">No jobs yet. Start scraping or training above.</p>
                    ) : (
                        <div className="job-table mt-2">
                            {recentJobs.map((job) => (
                                <div key={job.name} className="job-row">
                                    <div className="job-row-left">
                                        <span className={phaseChip(job.phase)}>
                                            {phaseIcon(job.phase)} {job.phase}
                                        </span>
                                        <span className="job-type-badge">{job.type}</span>
                                        <span className="job-name" title={job.name}>{job.name}</span>
                                    </div>
                                    <div className="job-row-right">
                                        {job.completion_time && (
                                            <span className="job-time text-muted small">
                                                {new Date(job.completion_time).toLocaleTimeString()}
                                            </span>
                                        )}
                                        <button
                                            className="btn btn-outline-primary btn-xs"
                                            onClick={() => openLogs(job.name)}
                                        >
                                            Logs
                                        </button>
                                        {job.phase === 'Running' ? (
                                            <button
                                                className="btn btn-outline-danger btn-xs"
                                                onClick={() => handleCancel(job.name)}
                                            >
                                                Cancel
                                            </button>
                                        ) : (
                                            <button
                                                className="btn btn-outline-secondary btn-xs"
                                                onClick={() => handleDelete(job.name)}
                                            >
                                                Delete
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* ── 4. Log viewer ────────────────────────────────────────── */}
                {logOpen && (
                    <div className="control-group mt-4">
                        <div className="d-flex align-items-center justify-content-between mb-2">
                            <p className="text-uppercase text-muted small mb-0">
                                Logs — <span className="log-job-name">{logJobName}</span>
                            </p>
                            <button
                                className="btn btn-outline-primary btn-xs"
                                onClick={closeLogs}
                            >
                                Close
                            </button>
                        </div>
                        <div className="log-viewer">
                            {logLines.length === 0 ? (
                                <span className="log-waiting">Waiting for output…</span>
                            ) : (
                                logLines.map((line, i) => (
                                    <div key={i} className="log-line">{line}</div>
                                ))
                            )}
                            <div ref={logEndRef} />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default TrainingPage;
