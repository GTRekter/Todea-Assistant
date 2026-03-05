import { useState, useEffect } from 'react';
import { saveProviderSettings, getSettingsStatus, getClusterSettings, saveClusterSettings } from '../services/agentHubApi';
import './settingsPage.css';

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

function ProviderForm({ title, description, fields, onSave }) {
    const [values, setValues] = useState(() => Object.fromEntries(fields.map(f => [f.key, ''])));
    const [showSecrets, setShowSecrets] = useState({});
    const [saveStatus, setSaveStatus] = useState(null);
    const [errorMessage, setErrorMessage] = useState('');

    const hasValues = fields.some(f => values[f.key]?.trim());

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!hasValues) return;
        setSaveStatus('saving');
        setErrorMessage('');
        try {
            const payload = {};
            for (const f of fields) {
                if (values[f.key]?.trim()) payload[f.payloadKey] = values[f.key].trim();
            }
            await onSave(payload);
            setSaveStatus('saved');
            setValues(Object.fromEntries(fields.map(f => [f.key, ''])));
        } catch (err) {
            setSaveStatus('error');
            setErrorMessage(err?.message || 'Failed to save.');
        }
    };

    return (
        <div className="control-group h-100">
            <p className="text-uppercase text-muted small mb-2">{title}</p>
            <p className="mb-0 text-muted">{description}</p>
            <form className="mt-3" onSubmit={handleSubmit}>
                {fields.map(f => (
                    <div key={f.key} className="mb-3">
                        <label className="form-label">{f.label}</label>
                        <div className={f.secret ? 'input-group stacked-input' : ''}>
                            <input
                                type={f.secret && !showSecrets[f.key] ? 'password' : 'text'}
                                className="form-control"
                                placeholder={f.placeholder || ''}
                                value={values[f.key]}
                                onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                                autoComplete="off"
                            />
                            {f.secret && (
                                <button
                                    type="button"
                                    className="btn btn-outline-secondary"
                                    onClick={() => setShowSecrets(s => ({ ...s, [f.key]: !s[f.key] }))}
                                    tabIndex={-1}
                                >
                                    {showSecrets[f.key] ? 'Hide' : 'Show'}
                                </button>
                            )}
                        </div>
                    </div>
                ))}
                {saveStatus === 'error' && (
                    <div className="feedback error mb-2">{errorMessage}</div>
                )}
                {saveStatus === 'saved' && (
                    <div className="feedback success mb-2">Saved successfully.</div>
                )}
                <button
                    type="submit"
                    className="btn btn-primary w-100 mt-1"
                    disabled={saveStatus === 'saving' || !hasValues}
                >
                    {saveStatus === 'saving' ? 'Saving…' : 'Save'}
                </button>
            </form>
        </div>
    );
}

const GOOGLE_FIELDS = [
    { key: 'googleApiKey', payloadKey: 'google_api_key', label: 'API key', placeholder: 'AIza…', secret: true },
];

const AZURE_FIELDS = [
    { key: 'azureEndpoint', payloadKey: 'azure_endpoint', label: 'Endpoint', placeholder: 'https://<resource>.openai.azure.com' },
    { key: 'azureApiKey', payloadKey: 'azure_api_key', label: 'API key', placeholder: '••••••••', secret: true },
    { key: 'azureDeployment', payloadKey: 'azure_deployment', label: 'Deployment name', placeholder: 'gpt-4o' },
    { key: 'azureApiVersion', payloadKey: 'azure_api_version', label: 'API version', placeholder: '2024-02-01' },
];

const OLLAMA_FIELDS = [
    { key: 'ollamaHost', payloadKey: 'ollama_host', label: 'Ollama host', placeholder: 'http://localhost:11434' },
];

const SettingsPage = () => {
    const [providers, setProviders] = useState({ google: false, azure: false, ollama: false });
    const [secretExists, setSecretExists] = useState(null);
    const [lastCheckedAt, setLastCheckedAt] = useState(null);

    const [kubeServer, setKubeServer] = useState('');
    const [kubeSaveStatus, setKubeSaveStatus] = useState(null);
    const [kubeStatus, setKubeStatus] = useState(null);

    const refreshStatus = async () => {
        try {
            const data = await getSettingsStatus();
            setSecretExists(data.exists);
            if (data.providers) setProviders(data.providers);
            setLastCheckedAt(Date.now());
        } catch {
            setSecretExists(false);
        }
    };

    useEffect(() => {
        refreshStatus();
        getClusterSettings()
            .then(({ kube_server }) => setKubeServer(kube_server || ''))
            .catch(() => {});
    }, []);

    const handleProviderSave = async (payload) => {
        await saveProviderSettings(payload);
        await refreshStatus();
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

    return (
        <div className="container full-height-container settings settings-page">
            <div className="panel-card text-white">
                <div className="row align-items-lg-center justify-content-between">
                    <div className="col-lg">
                        <p className="eyebrow text-uppercase">Configuration</p>
                        <h2>Settings</h2>
                        <p className="text-muted">
                            Manage AI provider credentials and cluster configuration.
                        </p>
                    </div>
                </div>

                <div className="col-12">
                    <div className="control-group mt-4">
                        <p className="text-uppercase text-muted small mb-2">Cluster status</p>
                        <p className="mb-0 text-muted">Quick view of the current provider configuration.</p>

                        <div className="row g-3 mt-1">
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Secret presence</p>
                                <small className="text-muted d-block mb-2">Looks for <code>todea-api-keys</code> in <code>todea</code>.</small>
                                <div className="mt-auto">
                                    {secretExists === true && <span className="status-chip configured">✓ Secret configured</span>}
                                    {secretExists === false && <span className="status-chip not-found">⚠ No secret found</span>}
                                    {secretExists === null && <span className="status-chip">–</span>}
                                </div>
                            </div>
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Google</p>
                                <small className="text-muted d-block mb-2">Gemini models via ADK.</small>
                                <div className="mt-auto">
                                    <span className={`status-chip ${providers.google ? 'configured' : 'not-found'}`}>
                                        {providers.google ? '✓ Configured' : '⚠ Not set'}
                                    </span>
                                </div>
                            </div>
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Azure OpenAI</p>
                                <small className="text-muted d-block mb-2">Azure-hosted GPT models.</small>
                                <div className="mt-auto">
                                    <span className={`status-chip ${providers.azure ? 'configured' : 'not-found'}`}>
                                        {providers.azure ? '✓ Configured' : '⚠ Not set'}
                                    </span>
                                </div>
                            </div>
                            <div className="col-12 col-md-3 d-flex flex-column">
                                <p className="mb-1 text-uppercase small">Ollama</p>
                                <small className="text-muted d-block mb-2">Local or remote Ollama instance.</small>
                                <div className="mt-auto">
                                    <span className={`status-chip ${providers.ollama ? 'configured' : 'not-found'}`}>
                                        {providers.ollama ? '✓ Configured' : '⚠ Not set'}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="row g-4 mt-2">
                    <div className="col-12 col-lg-4">
                        <ProviderForm
                            title="Google"
                            description="Gemini models via Google AI Studio. Stored as GOOGLE_API_KEY in the todea-api-keys secret."
                            fields={GOOGLE_FIELDS}
                            onSave={handleProviderSave}
                        />
                    </div>
                    <div className="col-12 col-lg-4">
                        <ProviderForm
                            title="Azure OpenAI"
                            description="Azure-hosted GPT models. Credentials stored in the todea-api-keys secret."
                            fields={AZURE_FIELDS}
                            onSave={handleProviderSave}
                        />
                    </div>
                    <div className="col-12 col-lg-4">
                        <ProviderForm
                            title="Ollama"
                            description="Connect to a local or remote Ollama instance. Leave blank to use http://localhost:11434."
                            fields={OLLAMA_FIELDS}
                            onSave={handleProviderSave}
                        />
                    </div>
                </div>

                <div className="row g-4 mt-2">
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
                                    <div className={`feedback mt-3 mb-0 ${kubeStatus.type === 'danger' ? 'error' : kubeStatus.type || ''}`}>
                                        {kubeStatus.message}
                                    </div>
                                )}
                                <button
                                    type="submit"
                                    className="btn btn-primary w-100 mt-3"
                                    disabled={kubeSaveStatus === 'saving'}
                                >
                                    {kubeSaveStatus === 'saving' ? 'Saving…' : 'Save endpoint'}
                                </button>
                            </form>
                        </div>
                    </div>
                    <div className="col-12 col-lg-6">
                        <div className="control-group h-100">
                            <p className="text-uppercase text-muted small mb-2">Sync</p>
                            <p className="mb-0 text-muted">Last time this page checked the cluster secret status.</p>
                            <div className="mt-3">
                                <p className="mb-1 text-uppercase small">Last checked</p>
                                <span className="status-chip">
                                    {lastCheckedAt ? formatTimestamp(lastCheckedAt) : '–'}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SettingsPage;
