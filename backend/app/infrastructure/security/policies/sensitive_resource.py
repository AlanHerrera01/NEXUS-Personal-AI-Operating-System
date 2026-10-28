import re

from app.domain.ports.policy import Policy
from app.domain.value_objects.policy_result import PolicyResult
from app.domain.value_objects.trust_context import TrustContext


class SensitiveResourcePolicy(Policy):
    """Deny access to sensitive resources like credentials, secrets, etc.

    Tool and skill names are the strong signal. Argument *keys* are scanned too:
    a tool that receives ``password`` or ``api_key`` is handling a credential
    whatever its name says.

    Argument *values* are only matched against credential-shaped strings. A raw
    substring check there denied ordinary requests -- a web search for "what is
    a token", or a URL containing the path ``/authentication`` -- without
    protecting anything: the value that matters is the secret, not the word.
    """

    SENSITIVE_KEYWORDS = frozenset({
        "credential", "password", "secret", "token", "api_key", "private_key",
        "ssh_key", "auth", "authentication", ".env", "keychain", "vault"
    })

    #: Shapes that are a secret rather than a sentence containing the word.
    _SECRET_PATTERNS = (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b"),
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
        # A credential in a URL query is a credential even when the surrounding
        # text is a legitimate URL.
        re.compile(
            r"(?i)[?&](?:token|access_token|id_token|api_key|apikey|secret|password)"
            r"=[^&\s]{8,}"
        ),
    )

    def evaluate(self, context: TrustContext) -> PolicyResult:
        # Check tool name for sensitive keywords
        tool_lower = context.tool_name.lower()
        skill_lower = context.skill_name.lower()

        for keyword in self.SENSITIVE_KEYWORDS:
            if keyword in tool_lower or keyword in skill_lower:
                return PolicyResult.deny(
                    self.policy_id,
                    f"Access to sensitive resource '{context.tool_name}' is prohibited"
                )

        for key, value in context.arguments.items():
            key_lower = key.lower()
            if any(keyword in key_lower for keyword in self.SENSITIVE_KEYWORDS):
                return PolicyResult.deny(
                    self.policy_id,
                    "Access to sensitive resource is prohibited"
                )
            if isinstance(value, str) and self._looks_like_secret(value):
                return PolicyResult.deny(
                    self.policy_id,
                    "Access to sensitive resource is prohibited"
                )

        return PolicyResult.not_applicable(self.policy_id)

    @classmethod
    def _looks_like_secret(cls, value: str) -> bool:
        return any(pattern.search(value) for pattern in cls._SECRET_PATTERNS)

    @property
    def policy_id(self) -> str:
        return "sensitive_resource"

    @property
    def priority(self) -> int:
        return 95  # Very high priority - protect sensitive resources
