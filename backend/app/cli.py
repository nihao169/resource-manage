"""B/C: explicit maintenance commands, never background startup migrations."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

def create_certificate(directory: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import ipaddress
    directory.mkdir(parents=True, exist_ok=True)
    key_file, cert_file = directory / "localhost.key", directory / "localhost.crt"
    if key_file.exists() or cert_file.exists():
        if not (key_file.exists() and cert_file.exists()):
            raise RuntimeError("Incomplete certificate pair; repair manually, do not overwrite.")
        key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
        if key.public_key().public_numbers() != cert.public_key().public_numbers():
            raise RuntimeError("Existing certificate does not match key")
        if cert.not_valid_after_utc <= datetime.now(timezone.utc):
            raise RuntimeError("Existing certificate expired; rotate manually.")
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if "localhost" not in san.get_values_for_type(x509.DNSName):
            raise RuntimeError("Existing certificate lacks localhost SAN")
        if ipaddress.ip_address("127.0.0.1") not in san.get_values_for_type(x509.IPAddress):
            raise RuntimeError("Existing certificate lacks loopback SAN")
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256()))
    # Exclusive creation: existing credentials are never overwritten.
    with key_file.open("xb") as stream:
        stream.write(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with cert_file.open("xb") as stream:
        stream.write(cert.public_bytes(serialization.Encoding.PEM))

def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    administrator = commands.add_parser("create-admin")
    administrator.add_argument("--username", required=True)
    administrator.add_argument("--display-name", required=True)
    administrator.add_argument("--password-file", type=Path, required=True)
    certificate = commands.add_parser("certificate")
    certificate.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "certificate":
        create_certificate(args.directory)
    elif args.command == "migrate":
        from alembic.config import Config
        from alembic import command
        command.upgrade(Config("alembic.ini"), "head")
    elif args.command == "create-admin":
        from sqlalchemy import text
        from app.core.config import Settings
        from app.core.database import create_database_engine
        from app.core.security import hash_password
        password = args.password_file.read_text(encoding="utf-8").strip()
        if not 12 <= len(password) <= 128:
            raise ValueError("Administrator password must contain 12-128 characters")
        engine = create_database_engine(Settings())
        try:
            with engine.begin() as connection:
                connection.execute(text("""
                    INSERT INTO users(username,display_name,password_hash,role)
                    VALUES (:username,:display_name,:password_hash,'admin')
                """), {"username": args.username.strip(), "display_name": args.display_name.strip(),
                    "password_hash": hash_password(password)})
        finally:
            engine.dispose()

if __name__ == "__main__":
    main()

