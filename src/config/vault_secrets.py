import os
import logging
from hvac import Client

logger = logging.getLogger(__name__)


def load_secrets() -> None:
    """
    Load secrets from Vault into environment variables.
    Works consistently in Local, Docker, and GitHub Actions and more secure to handle secrets
    Only requires:
      VAULT_ADDR  — where Vault is running
      VAULT_TOKEN — authentication token
    Both set externally per environment, never in code.
    """
    logger.info("Secrets are getting loaded")
    vault_address = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")
    secret_path = os.getenv("VAULT_SECRET_PATH", "")

    if not vault_address or not vault_token:
        raise ValueError(
            "VAULT_ADDR and VAULT_TOKEN must be set.\n"
            "  Local:   export VAULT_ADDR=... in your shell or set in user profile\n"
            "  Docker:  set in docker-compose.yml environment block\n"
            "  GitHub:  set in GitHub Secrets\n"
            "  These are the ONLY variables needed externally."
        )

    if not secret_path:
        raise ValueError("VAULT_SECRET_PATH must be set.")

    try:
        # Connect to vault
        client = Client(url=vault_address, token=vault_token)

        if not client.is_authenticated():
            logger.error(
                "Vault authentication failed - check token information for VAULT_TOKEN variable"
            )
            raise ValueError(
                "Vault authentication failed - check token information for VAULT_TOKEN variable"
            )

        paths = secret_path.split(",")
        for path in paths:
            # Read all secrets from vault
            response = client.secrets.kv.v2.read_secret_version(
                path=path.replace("secret/", ""), mount_point="secret"
            )
            secrets = response["data"]["data"]
            # Inject into environment variables
            for key, value in secrets.items():
                os.environ[key] = value
            logger.info(f" Secrets loaded from Vault: {list(secrets.keys())}")
        logger.info("Loading secrets completed")
    except Exception as e:
        logger.error(
            f"Exception while reading secrets from vault :- {e}", exc_info=True
        )
        raise ValueError(f"Exception while reading secrets from vault :- {e}")
