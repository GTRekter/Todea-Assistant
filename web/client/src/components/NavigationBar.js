import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './navigationBar.css';

const NAV_LINKS = [
    { label: 'Home', to: '/' },
    { label: 'Chat', to: '/gpt' },
    { label: 'Settings', to: '/settings' },
];

const NavigationBar = () => {
    const location = useLocation();
    const [isOpen, setIsOpen] = useState(false);

    const toggleMenu = () => setIsOpen((prev) => !prev);

    useEffect(() => {
        setIsOpen(false);
    }, [location.pathname]);

    return (
        <header className="site-navigation">
            <div className="container-fluid nav-inner">
                <Link className="brand-link" to="/">
                    <div className="brand-icon">📬</div>
                    <div>
                        <p className="brand-title mb-0">Todea</p>
                        <p className="brand-subtitle mb-0">Workspace Console</p>
                    </div>
                </Link>

                <button
                    className="nav-toggle d-lg-none"
                    type="button"
                    aria-label="Toggle navigation"
                    aria-expanded={isOpen}
                    onClick={toggleMenu}
                >
                    <span />
                    <span />
                    <span />
                </button>

                <nav className={`nav-links ${isOpen ? 'open' : ''}`}>
                    {NAV_LINKS.map((link) => {
                        const isActive = location.pathname === link.to;
                        return (
                            <Link key={link.to} className={`nav-link-pill ${isActive ? 'active' : ''}`} to={link.to}>
                                {link.label}
                            </Link>
                        );
                    })}
                </nav>

                <div className="nav-cta d-none d-lg-flex">
                    <Link to="/gpt" className="btn btn-primary btn-sm">
                        Open Chat
                    </Link>
                </div>
            </div>
        </header>
    );
};

export default NavigationBar;
