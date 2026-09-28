"""All database access. Callers use `from app import db` then `db.some_function()`;
each domain lives in its own module here and is re-exported below, so a new
function only needs adding to its module (and is picked up by the star import)."""
from .schema import MIGRATIONS, SCHEMA  # noqa: F401
from .core import *  # noqa: F401,F403
from .bills import *  # noqa: F401,F403
from .board import *  # noqa: F401,F403
from .mail_accounts import *  # noqa: F401,F403
from .mail_messages import *  # noqa: F401,F403
from .mail_bodies import *  # noqa: F401,F403
from .strokes import *  # noqa: F401,F403
from .settings import *  # noqa: F401,F403
from .lists import *  # noqa: F401,F403
from .users import *  # noqa: F401,F403
from .share import *  # noqa: F401,F403
from .badges import nav_counts  # noqa: F401
from .mail_accounts import _ACCOUNT_FIELDS  # noqa: F401
from .mail_messages import FLAG_FIELDS, MESSAGE_FIELDS, VIEW_WHERE  # noqa: F401
from .mail_bodies import BODY_CACHE_KEEP  # noqa: F401
