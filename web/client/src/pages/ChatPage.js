import Chat from '../components/Chat';

const ChatPage = () => {
    return (
        <div className="container full-height-container">
            <div className="text-white text-center py-5">
                <p className="eyebrow">Message Center</p>
                <h1>AI Workspace Assistant</h1>
                <p>Ask the assistant to surface hot topics, track channel activity, or update workspace settings. Multi-turn context keeps your conversation in sync.</p>
            </div>
            <Chat />
        </div>
    );
};

export default ChatPage;
