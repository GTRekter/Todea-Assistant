// Prefer a same-origin proxy path so the browser never has to reach the
// in-cluster service directly. Falls back to localhost for local dev when
// a training hub is running on the host.
const BASE_URL = (
    process.env.REACT_APP_TRAINING_HUB_URL || '/training-hub'
).replace(/\/$/, '');

async function request(method, path, body) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(`${BASE_URL}${path}`, opts);
    if (!res.ok) {
        let message = `HTTP ${res.status}`;
        try { message = (await res.json()).detail || message; } catch {}
        throw new Error(message);
    }
    return res.json();
}

export const getTrainingSettings = () => request('GET', '/settings');

export const saveGithubToken = (token) =>
    request('POST', '/settings/github-token', { token });

export const startScrape = (repos, websites) =>
    request('POST', '/scrape', { repos, websites });

export const startTrain = (model, adapterName, gpuNodePool) =>
    request('POST', '/train', {
        model,
        adapter_name: adapterName,
        gpu_node_pool: gpuNodePool,
    });

export const getJobs = () => request('GET', '/jobs');

export const cancelJob = (jobName) =>
    request('DELETE', `/jobs/${encodeURIComponent(jobName)}`);

/**
 * Open an SSE log stream for a job.
 * Returns the EventSource — caller must call .close() when done.
 *
 * @param {string} jobName
 * @param {(line: string) => void} onLine
 * @param {(err: Event) => void} [onError]
 */
export function streamLogs(jobName, onLine, onError) {
    const es = new EventSource(`${BASE_URL}/logs/${encodeURIComponent(jobName)}`);
    es.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.line) onLine(data.line);
        } catch {}
    };
    if (onError) es.onerror = onError;
    return es;
}
