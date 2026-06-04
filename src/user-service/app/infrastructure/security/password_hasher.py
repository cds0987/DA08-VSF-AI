import bcrypt


class BcryptPasswordHasher:
    def hash(self, plain_text: str) -> str:
        return bcrypt.hashpw(
            plain_text.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

    def verify(self, plain_text: str, hashed: str) -> bool:
        if not hashed:
            return False
        try:
            return bcrypt.checkpw(
                plain_text.encode("utf-8"),
                hashed.encode("utf-8"),
            )
        except ValueError:
            return False

