import React, { Component } from 'react';
import { Route } from 'react-router';
import { Layout } from './components/Layout';
import HomePage from './pages/HomePage';
import ChatPage from './pages/ChatPage';
import SettingsPage from './pages/SettingsPage';

export default class App extends Component {
    render () {
        return (
            <Layout>
                <Route exact path='/' component={HomePage} />
                <Route exact path='/gpt' component={ChatPage} />
                <Route exact path='/settings' component={SettingsPage} />
            </Layout>
        );
    }
}
