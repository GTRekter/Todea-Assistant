import os

from dotenv import load_dotenv

load_dotenv()

ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002/mcp")
CONVERSATION_HUB_URL = os.getenv("CONVERSATION_HUB_URL", "http://localhost:3300")
KUBE_NAMESPACE = os.getenv("KUBE_NAMESPACE", "todea")
KUBE_SECRET_NAME = os.getenv("KUBE_SECRET_NAME", "todea-api-keys")
PORT = int(os.environ.get("PORT", "3100"))
GOOGLE_MODEL = os.getenv("AGENT_MODEL_GOOGLE", "gemini-2.5-flash")
GOOGLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]
PROVIDER_ID = "google"
APP_NAME = "todea-google"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_API_KEY")
GOOGLE_VERTEX_PROJECT = os.getenv("GOOGLE_VERTEX_PROJECT") or os.getenv("VERTEX_PROJECT")
GOOGLE_VERTEX_LOCATION = os.getenv("GOOGLE_VERTEX_LOCATION") or os.getenv("VERTEX_LOCATION")
DEFAULT_INSTRUCTION = os.getenv(
    "DEFAULT_INSTRUCTION",
    (
        "You are the Todea workspace assistant. Think out loud, then answer concisely.\n"
        "You have tools for managing Buoyant Enterprise Linkerd (BEL) on Kubernetes.\n\n"
        "TOOL CALL RULES — follow these exactly:\n"
        "- Status / health check: call 'linkerd_check' or 'helm_status'. No arguments needed for linkerd_check.\n"
        "- Install Linkerd: follow this sequence in order, stop on any error:\n"
        "    1. helm_repo_add                — call with NO arguments (defaults are correct)\n"
        "    2. install_gateway_api_crds     — pass 'version' (e.g. '2.19.4')\n"
        "    3. helm_install_linkerd_crds    — pass 'version'\n"
        "    4. install_linkerd_control_plane — pass 'version' and 'license_key' ONLY\n"
        "    5. linkerd_check                — call with NO arguments to verify\n"
        "NEVER call generate_certificates or helm_install_linkerd_control_plane directly during an install — use install_linkerd_control_plane instead.\n"
        "Before starting an install, ask the user for the BEL version and license key if not provided.\n"
        "- Upgrade Linkerd: call helm_repo_add (no args), then helm_upgrade_linkerd.\n"
        "- Uninstall: call helm_status first to discover release names, then helm_uninstall_linkerd.\n\n"
        "NEVER call helm_*, linkerd_*, install_*, or generate_* tools in a different order than shown above.\n"
        "When calling any tool with no required arguments, pass an empty argument list."
    ),
)
