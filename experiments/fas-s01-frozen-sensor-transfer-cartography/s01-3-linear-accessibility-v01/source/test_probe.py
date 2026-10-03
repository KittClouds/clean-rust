from __future__ import annotations

import json

from linear_core import synthetic_self_test


if __name__ == "__main__":
    print(json.dumps(synthetic_self_test(), sort_keys=True))
