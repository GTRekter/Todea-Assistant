import { useState, useEffect } from 'react';
import { saveSettings, getSettingsStatus, getClusterSettings, saveClusterSettings } from '../services/agentHubApi';
import './settingsPage.css';

const STATUS_VARIANT = {
    info: 'info',
    success: 'success',
    warning: 'warning',
    danger: 'danger',
};

const formatTimestamp = (value) => {
    if (!value) return '';
    return new Intl.DateTimeFormat('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    }).format(new Date(value));
};

const SettingsPage = () => {
    const [googleApiKey, setGoogleApiKey] = useState('');
    const [showKey, setShowKey] = useState(false);
    const [saveStatus, setSaveStatus] = useState(null); // null | 'saving' | 'saved' | 'error'
    const [status, setStatus] = useState(null); // { type, message }
    const [errorMessage, setErrorMessage] = useState('');
    const [secretExists, setSecretExists] = useState(null); // null = loading
    const [isLoading, setIsLoading] = useState(false);
    const [lastCheckedAt, setLastCheckedAt] = useState(null);
    const [lastSavedAt, setLastSavedAt] = useState(null);

    const [kubeServer, setKubeServer] = useState('');
    const [kubeSaveStatus, setKubeSaveStatus] = useState(null); // null | 'saving' | 'saved' | 'error'
    const [kubeStatus, setKubeStatus] = useState(null); // { type, message }

    const refreshStatus = async () => {
        setIsLoading(true);
        setStatus(null);
        try {
            const { exists } = await getSettingsStatus();
            setSecretExists(exists);
            setLastCheckedAt(Date.now());
            setStatus({
                type: exists ? 'info' : 'warning',
            });
        } catch (err) {
            setSecretExists(false);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        refreshStatus();
        getClusterSettings()
            .then(({ kube_server }) => setKubeServer(kube_server || ''))
            .catch(() => {});
    }, []);

    const handleSave = async (e) => {
        if (e?.preventDefault) {
            e.preventDefault();
        }

        if (!googleApiKey.trim()) {
            setStatus({ type: 'warning', message: 'Add an API key before saving.' });
            return;
        }

        setSaveStatus('saving');
        setStatus(null);
        setErrorMessage('');
        try {
            await saveSettings({ googleApiKey });
            setSaveStatus('saved');
            setSecretExists(true);
            setGoogleApiKey('');
            const now = Date.now();
            setLastSavedAt(now);
            setStatus({ type: 'success', message: 'Secret saved to Kubernetes as todea-api-keys.' });
        } catch (err) {
            const message = err?.message || 'Failed to save secret.';
            setSaveStatus('error');
            setErrorMessage(message);
            setStatus({ type: 'danger', message });
        }
    };

    const handleSaveCluster = async (e) => {
        if (e?.preventDefault) e.preventDefault();
        setKubeSaveStatus('saving');
        setKubeStatus(null);
        try {
            await saveClusterSettings({ kubeServer });
            setKubeSaveStatus('saved');
            setKubeStatus({ type: 'success', message: kubeServer ? `Endpoint set to ${kubeServer}.` : 'Reverted to local cluster.' });
        } catch (err) {
            setKubeSaveStatus('error');
            setKubeStatus({ type: 'danger', message: err?.message || 'Failed to save cluster endpoint.' });
        }
    };

    const saveDisabled = saveStatus === 'saving' || !googleApiKey.trim();

    return (
        <div className="container full-height-container settings settings-page">
            <div className="panel-card text-white">
                <div className="row align-items-lg-center justify-content-between">
                    <div className="col-lg">
                        <p className="eyebrow text-uppercase">Configuration</p>
                        <h2>Settings</h2>
                        <p className="text-muted">
                            Manage API keys and cluster configuration.
                        </p>
                    </div>
                    <div className="col-lg-auto d-flex align-items-center gap-2">
                        <button
                            className="btn btn-outline-light"
                            type="button"
                            onClick={refreshStatus}
                            disabled={isLoading || saveStatus === 'saving'}
                        >
                            {isLoading ? 'Syncing…' : 'Refresh config'}
                        </button>
                        <button
                            className="btn btn-primary"
                            type="button"
                            onClick={handleSave}
                            disabled={saveDisabled}
                        >
                            {saveStatus === 'saving' ? 'Saving…' : 'Save'}
                        </button>
                    </div>
                </div>

                <div className="col-12">
                    <div className="control-group mt-4">
                        <p className="text-uppercase text-muted small mb-2">Cluster status</p>
                        <p className="mb-0 text-muted">Quick view of the current cluster state.</p>

                        <div className="row g-3 mt-1">
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Secret presence</p>
                                <small className="text-muted d-block mb-2">Looks for <code>todea-api-keys</code> in <code>todea</code>.</small>
                                <div className="mt-auto">
                                    {saveStatus === 'saved' && (
                                        <span className="status-chip configured">✓ Saved</span>
                                    )}
                                    {saveStatus === 'error' && (
                                        <span className="status-chip error" title={errorMessage}>⚠ Error</span>
                                    )}
                                    {saveStatus !== 'saved' && saveStatus !== 'error' && secretExists === true && (
                                        <span className="status-chip configured">✓ Secret configured</span>
                                    )}
                                    {saveStatus !== 'saved' && saveStatus !== 'error' && secretExists === false && (
                                        <span className="status-chip not-found">⚠ No secret found</span>
                                    )}
                                    {saveStatus !== 'saved' && saveStatus !== 'error' && secretExists === null && (
                                        <span className="status-chip">–</span>
                                    )}
                                </div>
                            </div>
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Sync window</p>
                                <small className="text-muted d-block mb-2">Use Refresh to re-check cluster state.</small>
                                    <div className="mt-auto">
                                    <span className="status-chip">
                                        {lastCheckedAt ? formatTimestamp(lastCheckedAt) : '–'}
                                    </span>
                                </div>
                            </div>
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Save status</p>
                                <small className="text-muted d-block mb-2">Track the latest key you deployed.</small>
                                <div className="mt-auto">
                                    {saveStatus === 'saved' && (
                                        <span className="status-chip configured">✓ Saved</span>
                                    )}
                                    {saveStatus === 'error' && (
                                        <span className="status-chip error">⚠ Error</span>
                                    )}
                                    {saveStatus !== 'saved' && saveStatus !== 'error' && (
                                        <span className="status-chip">Pending</span>
                                    )}
                                </div>
                            </div>
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Endpoint</p>
                                <small className="text-muted d-block mb-2">Active cluster API server.</small>
                                <div className="mt-auto">
                                    <span className="status-chip" title={kubeServer || 'local kubeconfig'}>
                                        {kubeServer || 'Local'}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="row g-4 mt-4">
                    <div className="col-12 col-lg-6">
                        <div className="control-group h-100">
                            <p className="text-uppercase text-muted small mb-2">Google API key</p>
                            <p className="mb-0 text-muted">
                                Stored as Kubernetes secret <code>todea-api-keys</code> in the <code>todea</code> namespace. Entering a new key overwrites the existing one.
                            </p>
                            <form className="mt-3" onSubmit={handleSave}>
                                <label className="form-label">API key</label>
                                <div className="input-group stacked-input">
                                    <input
                                        type={showKey ? 'text' : 'password'}
                                        className="form-control"
                                        placeholder="AIza…"
                                        value={googleApiKey}
                                        onChange={(e) => setGoogleApiKey(e.target.value)}
                                        autoComplete="off"
                                    />
                                    <button
                                        type="button"
                                        className="btn btn-outline-secondary"
                                        onClick={() => setShowKey((v) => !v)}
                                        tabIndex={-1}
                                    >
                                        {showKey ? 'Hide' : 'Show'}
                                    </button>
                                </div>

                                <button
                                    type="submit"
                                    className="btn btn-light w-100 mt-3"
                                    disabled={saveDisabled}
                                >
                                    {saveStatus === 'saving' ? 'Saving…' : 'Save key'}
                                </button>
                            </form>
                        </div>
                    </div>

                    <div className="col-12 col-lg-6">
                        <div className="control-group h-100">
                            <p className="text-uppercase text-muted small mb-2">Kubernetes endpoint</p>
                            <p className="mb-0 text-muted">
                                Override the cluster API server URL. Leave blank to use the local cluster from your default kubeconfig.
                            </p>

                            <form className="mt-3" onSubmit={handleSaveCluster}>
                                <label className="form-label">Cluster API server</label>
                                <input
                                    type="text"
                                    className="form-control"
                                    placeholder="https://localhost:6443 (local cluster)"
                                    value={kubeServer}
                                    onChange={(e) => setKubeServer(e.target.value)}
                                    autoComplete="off"
                                />

                                {kubeStatus && (
                                    <div className={`alert alert-${STATUS_VARIANT[kubeStatus.type] || 'secondary'} mt-3 mb-0`} role="alert">
                                        {kubeStatus.message}
                                    </div>
                                )}

                                <button
                                    type="submit"
                                    className="btn btn-light w-100 mt-3"
                                    disabled={kubeSaveStatus === 'saving'}
                                >
                                    {kubeSaveStatus === 'saving' ? 'Saving…' : 'Save endpoint'}
                                </button>
                            </form>
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
};

export default SettingsPage;
