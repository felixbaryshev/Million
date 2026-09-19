"""tokenomics -- measure and cut what Claude API traffic costs.

Three questions this answers, in order of how much money they tend to move:

1. What is my traffic actually costing me, broken down by prefix and tail?
   -> ``tokenomics analyze requests.jsonl``
2. Where is my prompt cache silently missing?
   -> ``tokenomics audit src/``
3. What would a change cost before I ship it?
   -> ``tokenomics estimate --input 40000 --output 800 --requests 10000``
"""

__version__ = "0.1.0"

from .cache import analyse
from .pricing import CATALOG, Cost, Model, Usage, get_model, price
from .tokens import count_api, estimate

__all__ = [
    "__version__",
    "analyse",
    "CATALOG",
    "Cost",
    "Model",
    "Usage",
    "count_api",
    "estimate",
    "get_model",
    "price",
]
