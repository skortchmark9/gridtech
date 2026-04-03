"""
Dispatch scenario analysis for Zone J steam-chiller demand response.

Shared data loading and marginal dispatch engine used by individual
scenario scripts. Each scenario defines WHEN the 500 MW DR is active;
the engine handles the hour-by-hour marginal displacement math.
"""
