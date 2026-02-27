import os

from dotenv import load_dotenv
from google.adk.agents import Agent

from .tools import generate_certificates, inspect_certificate, verify_certificate_chain

load_dotenv()
MODEL_NAME = os.getenv("AGENT_MODEL", "gemini-2.0-flash")

_INSTRUCTION = """
You are the Todea Certificate Agent. You generate, inspect, and verify X.509
certificates for use with Linkerd and other services.

You have three tools:

generate_certificates(trust_anchor_lifetime, issuer_lifetime)
  Generate a Linkerd-compatible trust anchor and issuer certificate pair.
  Returns JSON with 'ca_cert_pem', 'issuer_cert_pem', and 'issuer_key_pem'.
  Default lifetimes: trust anchor 10 years (87600h), issuer 1 year (8760h).

inspect_certificate(pem_content)
  Parse a PEM certificate and return its subject, issuer, validity dates,
  days remaining, CA flag, path length, SANs, and signature algorithm.

verify_certificate_chain(ca_cert_pem, cert_pem)
  Verify that cert_pem was signed by the CA in ca_cert_pem and report
  whether the chain is valid, the issuer DN matches, and both certs are
  unexpired.

Rules:
- Always return the full JSON output from each tool without modification.
- If a tool returns an 'error' key, report the exact error and stop.
- Never generate, invent, or modify PEM content yourself.
"""

openssl_agent = Agent(
    name="openssl_agent",
    model=MODEL_NAME,
    description=(
        "Generate Linkerd-compatible X.509 certificates (trust anchor + issuer pair) "
        "and inspect or verify certificate chains. "
        "Call this agent when you need to create, inspect, or validate certificates."
    ),
    instruction=_INSTRUCTION,
    tools=[generate_certificates, inspect_certificate, verify_certificate_chain],
)
