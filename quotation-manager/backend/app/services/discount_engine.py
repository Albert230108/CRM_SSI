"""
Discount Calculation Engine for Short-Stay Inn Quotation System

Ported near-verbatim from the desktop Quotation Manager
(Python-EmailQuotation-1/src/discount_engine.py). Only the config-file lookup
paths changed, to point at this service's bundled app/data/ directory instead
of a sibling-of-this-file layout. Behavior, caching, and the public API
(calculate_discount_for_booking) are unchanged.

Key Features:
- Multiple discount strategies (tier-based, percentage, seasonal, dynamic)
- Priority system for rule conflicts
- Backwards compatible with legacy pricing
- VAT-aware calculations
- Date range support for seasonal discounts
- Comprehensive logging and validation
"""

import json
import pathlib
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional, Any

# File paths - this module lives in app/services/, data files live in app/data/
DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
DISCOUNT_RULES_FILE = DATA_DIR / "discount_rules.json"
PRICING_FILE = DATA_DIR / "NewCombinedPrices.json"
BASE_PRICES_FILE = DATA_DIR / "base_prices.json"

# Global cache for loaded rules
_discount_rules_cache = None
_pricing_data_cache = None
_base_prices_cache = None


class DiscountCalculationError(Exception):
    """Custom exception for discount calculation errors"""
    pass


def load_discount_rules(force_reload=False) -> Dict:
    """
    Load discount rules from JSON file with caching.

    Args:
        force_reload: If True, bypass cache and reload from file

    Returns:
        Dictionary containing discount rules configuration
    """
    global _discount_rules_cache

    if _discount_rules_cache is not None and not force_reload:
        return _discount_rules_cache

    try:
        if DISCOUNT_RULES_FILE.exists():
            with open(DISCOUNT_RULES_FILE, 'r', encoding='utf-8') as f:
                _discount_rules_cache = json.load(f)
                return _discount_rules_cache
        else:
            # Return default configuration if file doesn't exist
            print(f"Warning: {DISCOUNT_RULES_FILE} not found, using default configuration")
            return get_default_discount_config()
    except Exception as e:
        print(f"Error loading discount rules: {e}")
        return get_default_discount_config()


def get_default_discount_config() -> Dict:
    """Return default discount configuration (legacy tier-based system)"""
    return {
        "version": "1.0.0",
        "global_settings": {
            "enabled": True,
            "priority_mode": "best_price",
            "fallback_to_tiers": True
        },
        "active_preset": "default",
        "presets": {
            "default": {
                "name": "Legacy Tier-Based",
                "active": True,
                "rules": [{
                    "id": "legacy_tier_based",
                    "type": "tier_based",
                    "name": "Standard Long Stay Discount",
                    "active": True,
                    "priority": 1,
                    "applies_to": {"properties": ["all"], "rooms": ["all"]},
                    "config": {"use_price_tiers": True}
                }]
            }
        }
    }


def load_pricing_data(force_reload=False) -> Dict:
    """Load pricing data from NewCombinedPrices.json with caching"""
    global _pricing_data_cache

    if _pricing_data_cache is not None and not force_reload:
        return _pricing_data_cache

    try:
        if PRICING_FILE.exists():
            with open(PRICING_FILE, 'r', encoding='utf-8') as f:
                _pricing_data_cache = json.load(f)
                return _pricing_data_cache
        else:
            print(f"Warning: {PRICING_FILE} not found")
            return {}
    except Exception as e:
        print(f"Error loading pricing data: {e}")
        return {}


def load_base_prices(force_reload=False) -> Dict:
    """
    Load base prices from base_prices.json with caching.

    Base prices are used by the Discount Manager as the foundation
    for all discount calculations, separate from Price Manager tiers.

    Returns:
        Dictionary containing base prices for all properties and rooms
    """
    global _base_prices_cache

    if _base_prices_cache is not None and not force_reload:
        return _base_prices_cache

    try:
        if BASE_PRICES_FILE.exists():
            with open(BASE_PRICES_FILE, 'r', encoding='utf-8') as f:
                _base_prices_cache = json.load(f)
                return _base_prices_cache
        else:
            print(f"Warning: {BASE_PRICES_FILE} not found, will use Price Manager fallback")
            return {}
    except Exception as e:
        print(f"Error loading base prices: {e}")
        return {}


def get_base_price(property_name: str, room_name: str, pricing_data: Optional[Dict] = None) -> float:
    """
    Get base price for a room from base_prices.json.

    If not found, falls back to 7-night tier from Price Manager.

    Args:
        property_name: Property name
        room_name: Room name
        pricing_data: Optional pricing data (for fallback)

    Returns:
        Base price per night
    """
    base_prices = load_base_prices()

    # Try to get from base_prices.json
    try:
        return base_prices['properties'][property_name][room_name]['base_price']
    except (KeyError, TypeError):
        # Fallback: use 7-night tier from Price Manager
        if pricing_data:
            try:
                # Try current year first
                year_key = str(datetime.now().year)
                if year_key in pricing_data:
                    room_data = pricing_data[year_key].get(property_name, {}).get(room_name, {})
                    price_tiers = room_data.get('price_tiers', {})
                    if '7' in price_tiers:
                        return price_tiers['7']

                # Try 2025 as fallback
                if '2025' in pricing_data:
                    room_data = pricing_data['2025'].get(property_name, {}).get(room_name, {})
                    price_tiers = room_data.get('price_tiers', {})
                    if '7' in price_tiers:
                        return price_tiers['7']
            except (KeyError, TypeError):
                pass

        print(f"Warning: No base price found for {property_name}/{room_name}, using 0")
        return 0.0


def check_date_in_ranges(check_date: date, date_ranges: List[Dict]) -> bool:
    """
    Check if a date falls within any of the specified date ranges.

    Args:
        check_date: Date to check
        date_ranges: List of date range dicts with start_month, start_day, end_month, end_day

    Returns:
        True if date is in any range
    """
    if not date_ranges:
        return True  # No restrictions means always applicable

    for date_range in date_ranges:
        start_month = date_range.get('start_month')
        start_day = date_range.get('start_day')
        end_month = date_range.get('end_month')
        end_day = date_range.get('end_day')

        # Create date objects for comparison (using current year as reference)
        year = check_date.year
        start_date = date(year, start_month, start_day)
        end_date = date(year, end_month, end_day)

        # Handle year wrap-around (e.g., Nov-Feb)
        if start_date > end_date:
            if check_date >= start_date or check_date <= end_date:
                return True
        else:
            if start_date <= check_date <= end_date:
                return True

    return False


def rule_applies_to_booking(rule: Dict, property_name: str, room_name: str,
                            nights: int, checkin_date: Optional[date] = None) -> bool:
    """
    Check if a discount rule applies to a specific booking.

    Args:
        rule: Discount rule dictionary
        property_name: Property name
        room_name: Room name
        nights: Number of nights
        checkin_date: Check-in date (optional, for seasonal rules)

    Returns:
        True if rule applies
    """
    if not rule.get('active', True):
        return False

    # Check property/room restrictions
    applies_to = rule.get('applies_to', {})
    properties = applies_to.get('properties', ['all'])
    rooms = applies_to.get('rooms', ['all'])

    if 'all' not in properties and property_name not in properties:
        return False

    if 'all' not in rooms and room_name not in rooms:
        return False

    # Check nights conditions
    conditions = rule.get('conditions', {})
    min_nights = conditions.get('min_nights', 0)
    max_nights = conditions.get('max_nights')

    if nights < min_nights:
        return False

    if max_nights is not None and nights > max_nights:
        return False

    # Check date ranges (for seasonal rules)
    if checkin_date:
        date_ranges = applies_to.get('date_ranges', [])
        if date_ranges and not check_date_in_ranges(checkin_date, date_ranges):
            return False

    return True


def calculate_tier_based_percentage_discount(nights: int, base_price: float,
                                               tier_config: Dict) -> Tuple[float, str]:
    """
    Calculate discount using tier-based percentage discounts.

    Each tier defines a minimum number of nights and a discount percentage to apply.
    The system checks tiers from highest to lowest and applies the first matching tier.

    Args:
        nights: Number of nights
        base_price: Base price per night from base_prices.json
        tier_config: Tier configuration with 'tiers' list

    Returns:
        Tuple of (discounted_price_per_night, description)
    """
    tiers = tier_config.get('tiers', [])
    # Tiers should already be sorted descending by min_nights

    for tier in tiers:
        if nights >= tier.get('min_nights', 0):
            discount_percentage = tier.get('discount_percentage', 0)
            discount_amount = base_price * (discount_percentage / 100.0)
            discounted_price = base_price - discount_amount
            description = tier.get('description', f"{discount_percentage}% tier discount")
            return discounted_price, description

    return base_price, "No discount (no tier matched)"


def calculate_tier_based_price_discount(nights: int, base_price: float, price_tiers: Dict,
                                        tier_config: Dict = None) -> Tuple[float, str]:
    """
    Calculate discount using Price Manager tier pricing.

    This references the Price Manager's tier system and uses whichever tier price is lower than the base price.

    Args:
        nights: Number of nights
        base_price: Base price per night from base_prices.json
        price_tiers: Dictionary of price tiers from Price Manager {"7": price, "28": price, "56": price}
        tier_config: Optional configuration with 'tier_keys' to specify which tiers to check

    Returns:
        Tuple of (discounted_price_per_night, description)
    """
    # Get tier keys from config, or use defaults
    if tier_config and 'tier_keys' in tier_config:
        tier_keys = [str(k) for k in tier_config['tier_keys']]
        # Sort by night count descending
        tier_keys = sorted(tier_keys, key=lambda x: int(x), reverse=True)
    else:
        # Default tiers: 56, 28, 7
        tier_keys = ['56', '28', '7']

    for tier_key in tier_keys:
        tier_nights = int(tier_key)
        if nights >= tier_nights and tier_key in price_tiers:
            tier_price = price_tiers[tier_key]

            # Only apply if tier price is lower than base
            if tier_price < base_price:
                return tier_price, f"Price Manager {tier_key}-night tier"

    return base_price, "No discount (Price Manager tiers not lower)"


def calculate_custom_tier_pricing(nights: int, base_price: float, custom_tier_config: Dict = None) -> Tuple[float, str]:
    """
    Calculate discount using custom-defined tier pricing in Discount Manager.

    This allows users to define their own night thresholds and prices independently of the Price Manager.
    The system will find the best matching tier for the given stay length and use that price if it's lower than base.

    Args:
        nights: Number of nights
        base_price: Base price per night
        custom_tier_config: Configuration with 'price_tiers' array: [{"nights": 7, "price": 65.0}, ...]

    Returns:
        Tuple of (discounted_price_per_night, description)
    """
    if not custom_tier_config or 'price_tiers' not in custom_tier_config:
        return base_price, "No custom tiers defined"

    price_tiers = custom_tier_config['price_tiers']
    if not price_tiers:
        return base_price, "No custom tiers defined"

    # Sort tiers by nights descending (check longest stays first)
    sorted_tiers = sorted(price_tiers, key=lambda t: t.get('nights', 0), reverse=True)

    # Find the first (highest) tier that matches
    for tier in sorted_tiers:
        tier_nights = tier.get('nights', 0)
        tier_price = tier.get('price', 0)

        if nights >= tier_nights and tier_price > 0:
            # Only apply if tier price is lower than base
            if tier_price < base_price:
                return tier_price, f"Custom {tier_nights}-night tier (€{tier_price:.2f}/night)"

    return base_price, "No custom tier discount (base price is lower)"


def calculate_percentage_discount(base_price: float, nights: int,
                                  percentage_config: Dict) -> Tuple[float, str]:
    """
    Calculate percentage-based discount.

    Args:
        base_price: Base price per night
        nights: Number of nights
        percentage_config: Percentage configuration from rule

    Returns:
        Tuple of (discounted_price_per_night, description)
    """
    percentage_tiers = percentage_config.get('percentage_tiers', [])
    sorted_tiers = sorted(percentage_tiers, key=lambda t: t.get('min_nights', 0), reverse=True)

    for tier in sorted_tiers:
        if nights >= tier.get('min_nights', 0):
            percentage = tier.get('percentage', 0)
            discount_amount = base_price * (percentage / 100.0)
            discounted_price = base_price - discount_amount
            description = tier.get('description', f"{percentage}% discount")
            return discounted_price, description

    return base_price, "No percentage discount applied"


def calculate_seasonal_discount(base_price: float, seasonal_config: Dict) -> Tuple[float, str]:
    """
    Calculate seasonal discount.

    Args:
        base_price: Base price per night
        seasonal_config: Seasonal configuration from rule

    Returns:
        Tuple of (discounted_price_per_night, description)
    """
    percentage = seasonal_config.get('discount_percentage', 0)
    discount_amount = base_price * (percentage / 100.0)
    discounted_price = base_price - discount_amount
    description = f"Seasonal discount ({percentage}%)"
    return discounted_price, description


def calculate_dynamic_discount(base_price: float, price_tiers: Dict,
                               dynamic_config: Dict) -> Tuple[float, str]:
    """
    Calculate dynamic discount based on comparison to highest price.

    Args:
        base_price: Base price per night
        price_tiers: Dictionary of price tiers
        dynamic_config: Dynamic configuration from rule

    Returns:
        Tuple of (price_per_night, description)
    """
    comparison_tier = dynamic_config.get('comparison_tier', '7')
    highest_price = price_tiers.get(str(comparison_tier), base_price)

    if base_price < highest_price:
        percentage_below = ((highest_price - base_price) / highest_price) * 100
        min_percentage = dynamic_config.get('min_percentage_below', 5.0)

        if percentage_below >= min_percentage:
            description = f"Market discount ({percentage_below:.1f}% below standard)"
            return base_price, description

    return base_price, "No dynamic discount applied"


def calculate_discount_for_booking(
    room_name: str,
    property_name: str,
    nights: int,
    checkin_date: Optional[date],
    base_price_per_night: float,
    pricing_data: Dict,
    discount_rules: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Main function to calculate discount for a booking with priority handling.

    This function implements the hybrid architecture:
    1. Uses base prices from base_prices.json as foundation for discount calculations
    2. Applies discount rules on top of base prices
    3. Gets tier price from Price Manager based on nights
    4. Compares both and returns the best (lowest) price

    Args:
        room_name: Room name
        property_name: Property name
        nights: Number of nights
        checkin_date: Check-in date
        base_price_per_night: Legacy parameter (kept for compatibility, not used)
        pricing_data: Full pricing data dictionary from Price Manager
        discount_rules: Discount rules (loaded if None)

    Returns:
        Dictionary with discount calculation results
    """
    if discount_rules is None:
        discount_rules = load_discount_rules()

    # Get base price from base_prices.json (with fallback to Price Manager)
    base_price_from_file = get_base_price(property_name, room_name, pricing_data)

    # Get price tier from Price Manager based on nights
    year_key = str(checkin_date.year) if checkin_date else "2025"
    property_data = pricing_data.get(year_key, {}).get(property_name, {})
    room_data = property_data.get(room_name, {})
    price_tiers = room_data.get('price_tiers', {})

    # Determine which tier to use based on nights
    tier_price = base_price_from_file  # Default fallback
    if nights >= 56 and '56' in price_tiers:
        tier_price = price_tiers['56']
    elif nights >= 28 and '28' in price_tiers:
        tier_price = price_tiers['28']
    elif '7' in price_tiers:
        tier_price = price_tiers['7']

    # Check if discount system is enabled
    if not discount_rules.get('global_settings', {}).get('enabled', True):
        # Discount system disabled, use tier price from Price Manager
        return {
            'original_price': base_price_from_file,
            'discounted_price': tier_price,
            'discount_per_night': tier_price - base_price_from_file,
            'discount_description': 'Discount system disabled (using Price Manager)',
            'rule_applied': None,
            'rule_type': None,
            'priority': 0,
            'base_price_source': 'base_prices.json',
            'tier_price': tier_price,
            'using_tier_price': True
        }

    # Get active preset
    active_preset_name = discount_rules.get('active_preset', 'default')
    presets = discount_rules.get('presets', {})
    active_preset = presets.get(active_preset_name, {})

    # Check if preset is enabled (fallback to 'active' for backward compatibility)
    if not active_preset.get('enabled', active_preset.get('active', True)):
        # Fallback to default if active preset is disabled
        active_preset = presets.get('default', {})

    # Get rules from active preset
    rules = active_preset.get('rules', [])

    # Filter applicable rules
    applicable_rules = [
        rule for rule in rules
        if rule_applies_to_booking(rule, property_name, room_name, nights, checkin_date)
    ]

    if not applicable_rules:
        # No discount rules apply, compare tier price with base price
        final_price = min(tier_price, base_price_from_file)
        using_tier = (tier_price < base_price_from_file)

        return {
            'original_price': base_price_from_file,
            'discounted_price': final_price,
            'discount_per_night': final_price - base_price_from_file,
            'discount_description': 'Price Manager tier' if using_tier else 'Base price (no discounts)',
            'rule_applied': None,
            'rule_type': None,
            'priority': 0,
            'base_price_source': 'base_prices.json',
            'tier_price': tier_price,
            'using_tier_price': using_tier
        }

    # Calculate discounts for all applicable rules using BASE PRICE as foundation
    discount_results = []

    for rule in applicable_rules:
        rule_type = rule.get('type', 'tier_based')
        rule_config = rule.get('config', {})
        rule_name = rule.get('name', 'Unnamed rule')
        rule_priority = rule.get('priority', 0)

        try:
            if rule_type == 'tier_based_percentage':
                # Use base price and apply percentage discounts based on night tiers
                discounted_price, description = calculate_tier_based_percentage_discount(
                    nights, base_price_from_file, rule_config
                )
            elif rule_type == 'tier_based_price':
                # Reference Price Manager tier pricing
                discounted_price, description = calculate_tier_based_price_discount(
                    nights, base_price_from_file, price_tiers, rule_config
                )
            elif rule_type == 'custom_tier_pricing':
                # Use custom-defined tier pricing from Discount Manager
                discounted_price, description = calculate_custom_tier_pricing(
                    nights, base_price_from_file, rule_config
                )
            elif rule_type == 'percentage':
                discounted_price, description = calculate_percentage_discount(
                    base_price_from_file, nights, rule_config
                )
            elif rule_type == 'seasonal':
                discounted_price, description = calculate_seasonal_discount(
                    base_price_from_file, rule_config
                )
            else:
                print(f"Unknown rule type: {rule_type}")
                continue

            discount_results.append({
                'rule_id': rule.get('id'),
                'rule_name': rule_name,
                'rule_type': rule_type,
                'priority': rule_priority,
                'original_price': base_price_from_file,
                'discounted_price': discounted_price,
                'discount_per_night': discounted_price - base_price_from_file,
                'discount_description': description
            })

        except Exception as e:
            print(f"Error calculating discount for rule {rule_name}: {e}")
            continue

    if not discount_results:
        # No valid discounts, compare tier price with base price
        final_price = min(tier_price, base_price_from_file)
        using_tier = (tier_price < base_price_from_file)

        return {
            'original_price': base_price_from_file,
            'discounted_price': final_price,
            'discount_per_night': final_price - base_price_from_file,
            'discount_description': 'Price Manager tier' if using_tier else 'Base price (no valid discounts)',
            'rule_applied': None,
            'rule_type': None,
            'priority': 0,
            'base_price_source': 'base_prices.json',
            'tier_price': tier_price,
            'using_tier_price': using_tier
        }

    # Apply priority strategy to select best discount rule
    priority_mode = discount_rules.get('global_settings', {}).get('priority_mode', 'best_price')

    if priority_mode == 'best_price':
        # Choose the discount that gives the lowest final price
        selected = min(discount_results, key=lambda r: r['discounted_price'])
    elif priority_mode == 'highest_priority':
        # Choose the rule with the highest priority number
        selected = max(discount_results, key=lambda r: r['priority'])
    elif priority_mode == 'first_match':
        # Use the first rule that matched
        selected = discount_results[0]
    elif priority_mode == 'stack_discounts':
        # Stack multiple discounts (dangerous!)
        max_combined = discount_rules.get('priority_strategies', {}).get('stack_discounts', {}).get('max_combined_discount', 30.0)
        total_discount_percent = 0
        for result in discount_results:
            discount_percent = abs((result['discount_per_night'] / base_price_from_file) * 100)
            total_discount_percent += discount_percent

        if total_discount_percent > max_combined:
            total_discount_percent = max_combined

        final_price = base_price_from_file * (1 - total_discount_percent / 100)
        selected = {
            'rule_id': 'stacked',
            'rule_name': 'Combined Discounts',
            'rule_type': 'stacked',
            'priority': 0,
            'original_price': base_price_from_file,
            'discounted_price': final_price,
            'discount_per_night': final_price - base_price_from_file,
            'discount_description': f'Stacked discounts ({total_discount_percent:.1f}% total)'
        }
    else:
        # Default to best price
        selected = min(discount_results, key=lambda r: r['discounted_price'])

    # CRITICAL: Compare discount result with Price Manager tier price
    # Always use the BEST (lowest) price for the customer
    discount_price = selected['discounted_price']
    using_tier_price = tier_price < discount_price
    final_price = min(tier_price, discount_price)

    # Build description explaining which price won
    if using_tier_price:
        final_description = f"Price Manager tier (better than {selected['discount_description']})"
    else:
        final_description = selected['discount_description']

    return {
        'original_price': base_price_from_file,
        'discounted_price': final_price,
        'discount_per_night': final_price - base_price_from_file,
        'discount_description': final_description,
        'rule_applied': None if using_tier_price else selected['rule_name'],
        'rule_type': None if using_tier_price else selected['rule_type'],
        'rule_id': None if using_tier_price else selected.get('rule_id'),
        'priority': 0 if using_tier_price else selected['priority'],
        'base_price_source': 'base_prices.json',
        'tier_price': tier_price,
        'using_tier_price': using_tier_price,
        'discount_manager_price': discount_price,  # For comparison/debugging
        'discount_manager_description': selected['discount_description']  # Original discount description
    }


def is_discount_system_enabled() -> bool:
    """Check if discount system is enabled"""
    rules = load_discount_rules()
    return rules.get('global_settings', {}).get('enabled', True)


def get_active_preset_name() -> str:
    """Get name of active discount preset"""
    rules = load_discount_rules()
    preset_name = rules.get('active_preset', 'default')
    preset = rules.get('presets', {}).get(preset_name, {})
    return preset.get('name', preset_name)


def get_priority_mode() -> str:
    """Get current priority mode"""
    rules = load_discount_rules()
    return rules.get('global_settings', {}).get('priority_mode', 'best_price')
