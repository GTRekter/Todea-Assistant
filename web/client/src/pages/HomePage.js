import { Link } from 'react-router-dom';
import linkyImage from '../images/linky.png';
import './homePage.css';

const FEATURE_CARDS = [
    {
        label: '💬 Chat with Linky',
        description: 'Ask questions in plain language. Multi-turn context keeps the conversation flowing across your Linkerd inspection sessions.',
        actionLabel: 'Open chat',
        to: '/gpt',
    },
    {
        label: '🔍 Inspect service health',
        description: 'Run linkerd check, view traffic stats, and surface error rates or latency spikes across your mesh — all without touching kubectl.',
        actionLabel: 'Check health',
        to: '/gpt',
    },
    {
        label: '🔒 Analyze traffic & TLS',
        description: 'Explore per-route metrics, mTLS edge connectivity, certificate identities, and raw proxy metrics through natural language.',
        actionLabel: 'Analyze traffic',
        to: '/gpt',
    },
];

const SETUP_PANELS = [
    {
        icon: '🔗',
        label: 'Set up Linkerd CLI',
        steps: [
            <>Install the Linkerd CLI: <code>curl --proto '=https' --tlsv1.2 -sSfL https://run.linkerd.io/install | sh</code> and add it to your <code>$PATH</code>.</>,
            <>Validate your Kubernetes cluster: <code>linkerd check --pre</code>.</>,
            <>Install Linkerd onto the cluster: <code>linkerd install --crds | kubectl apply -f -</code> then <code>linkerd install | kubectl apply -f -</code>.</>,
            <>Install the viz extension: <code>linkerd viz install | kubectl apply -f -</code>, then verify with <code>linkerd check</code>.</>,
        ],
    },
];

const STEPS = [
    'Open the chat and describe what you want — check mesh health, query traffic stats, inspect TLS edges, or debug a specific pod.',
    'Linky routes your request through an MCP agent to the Linkerd CLI and returns a plain-language response.',
    'Iterate on prompts or use the refresh button to start a fresh conversation at any time.',
];

const STATS = [
    { label: 'AI provider', value: 'Gemini', sub: 'Google Gemini via ADK' },
    { label: 'Session memory', value: 'Per tab', sub: 'Scoped session ID for continuity' },
    { label: 'Reset control', value: 'One click', sub: 'Clear messages instantly' },
];

const HomePage = () => {
    return (
        <div className="full-height-container text-white">
            <div className="container">

                <section className="row align-items-center">
                    <div className="col-12 col-lg-6 offset-lg-1">
                        <p className="eyebrow text-uppercase mb-2">Todea-Assistant</p>
                        <h1>Chat with Linky to explore your service mesh</h1>
                        <p className="lead text-white">
                            Inspect Linkerd health, analyze traffic metrics, and debug TLS connectivity — all through a natural language interface powered by Google Gemini.
                        </p>
                        <div className="row mt-4">
                            <div className="col-auto">
                                <Link to="/gpt" className="btn btn-primary btn-lg">
                                    Open the chat
                                </Link>
                            </div>
                            <div className="col-auto">
                                <a href="#how-it-works" className="btn btn-outline-light btn-lg">
                                    How it works
                                </a>
                            </div>
                        </div>
                    </div>
                    <div className="col-12 col-lg-5">
                        <div className="linkerd-card">
                            <img src={linkyImage} alt="Linky mascot" className="icon" />
                            <ul className="callouts">
                                <li>Traffic stats and error rate analysis</li>
                                <li>Session memory per provider</li>
                                <li>Reset anytime with one click</li>
                            </ul>
                        </div>
                    </div>
                </section>

                <section className="row statistics">
                    {STATS.map((stat) => (
                        <div className="col-12 col-lg-4 my-4" key={stat.label}>
                            <div className="card p-4 text-center">
                                <p className="fs-1 fw-bold mb-1">{stat.value}</p>
                                <p className="text-uppercase text-white-50 small mb-1">{stat.label}</p>
                                <p className="text-white-50 mb-0">{stat.sub}</p>
                            </div>
                        </div>
                    ))}
                </section>

                <section className="row features">
                    {FEATURE_CARDS.map((feature) => (
                        <div className="col-12 col-lg-4 my-4" key={feature.label}>
                            <div className="card p-4 text-center">
                                <p className="h5 fw-semibold mb-2">{feature.label}</p>
                                <p className="text-white-50 mb-3">{feature.description}</p>
                                <Link className="stretched-link text-decoration-none" to={feature.to}>
                                    {feature.actionLabel} →
                                </Link>
                            </div>
                        </div>
                    ))}
                </section>

                <section className="row steps" id="how-it-works">
                    <div className="col-12">
                        <div className="card">
                            <p className="eyebrow mb-2">How it works</p>
                            <h2>From request to action in minutes</h2>
                            <ol>
                                {STEPS.map((step, idx) => (
                                    <li key={step}>
                                        <span className="index">{idx + 1}</span>
                                        <p>{step}</p>
                                    </li>
                                ))}
                            </ol>
                        </div>
                    </div>
                </section>

                <section className="row setup" id="setup">
                    <div className="col-12 mb-4">
                        <p className="eyebrow mb-2">Configuration</p>
                        <h2>Connect your services</h2>
                    </div>
                    {SETUP_PANELS.map((panel) => (
                        <div className="col-12 col-lg-6 mb-4" key={panel.label}>
                            <div className="card h-100">
                                <p className="h5 fw-semibold mb-3">{panel.icon} {panel.label}</p>
                                <ol>
                                    {panel.steps.map((step, idx) => (
                                        <li key={idx}>
                                            <span className="index">{idx + 1}</span>
                                            <p>{step}</p>
                                        </li>
                                    ))}
                                </ol>
                            </div>
                        </div>
                    ))}
                </section>

            </div>
        </div>
    );
};

export default HomePage;
