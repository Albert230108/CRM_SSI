"""
Admin cost calculation, ported from the desktop Quotation Manager
(Python-EmailQuotation-1/src/functions.py). Only the config-file lookup path
changed to point at this service's bundled app/data/ directory. save_admin_costs
is intentionally not ported - there is no settings-editor UI in this MVP, so
admin_costs.json is read-only here.
"""

import json
import pathlib
from datetime import datetime

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
ADMIN_COSTS_FILE = DATA_DIR / "admin_costs.json"

_admin_costs_cache = None


def load_admin_costs(force_reload=False):
    """
    Load admin costs configuration from admin_costs.json

    Args:
        force_reload: If True, reload from file even if cached

    Returns:
        Dictionary with property admin cost settings
    """
    global _admin_costs_cache

    if _admin_costs_cache is not None and not force_reload:
        return _admin_costs_cache

    try:
        if ADMIN_COSTS_FILE.exists():
            with open(ADMIN_COSTS_FILE, 'r', encoding='utf-8') as f:
                _admin_costs_cache = json.load(f)
            return _admin_costs_cache
        else:
            print("Warning: admin_costs.json not found, using defaults")
            return get_default_admin_costs()

    except Exception as e:
        print(f"Error loading admin costs: {e}")
        return get_default_admin_costs()


def get_default_admin_costs():
    """Return default admin costs configuration"""

    return {
        "version": "1.0",
        "last_updated": datetime.now().strftime('%Y-%m-%d'),
        "properties": {
            property_name: {
                "admin_costs_enabled": True,
                "admin_percentage": 5.0,
                "admin_min": 15.00,
                "admin_max": 50.00,
                "description": f"{property_name} administration fee"
            }
            for property_name in [
                "Central-Day Inn",
                "Ensche-Day Inn",
                "Blekerstraat",
                "Atjehstraat",
                "Hoogstraat 69",
                "Guest information"
            ]
        }
    }


def get_admin_costs_for_property(property_name):
    """
    Get admin costs settings for a specific property

    Args:
        property_name: Name of property

    Returns:
        Dictionary with admin_percentage, admin_min, admin_max
    """
    admin_costs = load_admin_costs()

    if property_name in admin_costs.get('properties', {}):
        return admin_costs['properties'][property_name]
    else:
        # Return defaults if property not found
        return {
            "admin_costs_enabled": True,
            "admin_percentage": 5.0,
            "admin_min": 15.00,
            "admin_max": 50.00,
            "description": f"{property_name} administration fee"
        }


def calculate_admin_costs(property_name, total_charges, deposit_amount, city_tax_amount):
    """
    Calculate admin costs based on charges, with min/max limits

    Formula:
    Admin = (Total Charges - Deposit - City Tax) x Percentage%
    Clamped between Min and Max

    Args:
        property_name: Name of property
        total_charges: Total charges (all items)
        deposit_amount: Security deposit amount
        city_tax_amount: City tax amount

    Returns:
        Dictionary with admin_cost, base_amount, percentage, min_limit, max_limit, description
    """

    # Get admin cost settings for property
    admin_settings = get_admin_costs_for_property(property_name)

    # Check if enabled
    if not admin_settings.get('admin_costs_enabled', True):
        return {
            'admin_cost': 0.0,
            'base_amount': 0.0,
            'percentage': 0.0,
            'min_limit': 0.0,
            'max_limit': 0.0,
            'description': 'Admin costs disabled',
            'clamped': False,
            'property_name': property_name
        }

    # Calculate base amount (charges - deposit - city tax)
    base_amount = total_charges - deposit_amount - city_tax_amount

    # Ensure base amount is not negative
    if base_amount < 0:
        base_amount = 0.0

    # Get percentage and limits
    percentage = admin_settings.get('admin_percentage', 5.0)
    min_limit = admin_settings.get('admin_min', 15.0)
    max_limit = admin_settings.get('admin_max', 50.0)

    # Calculate raw admin cost
    raw_admin_cost = base_amount * (percentage / 100.0)

    # Apply min/max limits
    final_admin_cost = max(min_limit, min(raw_admin_cost, max_limit))

    # Return detailed result
    return {
        'admin_cost': round(final_admin_cost, 2),
        'base_amount': round(base_amount, 2),
        'raw_admin_cost': round(raw_admin_cost, 2),
        'percentage': percentage,
        'min_limit': min_limit,
        'max_limit': max_limit,
        'clamped': final_admin_cost != raw_admin_cost,
        'description': f"Admin costs: {percentage}% of €{base_amount:.2f} "
                      f"= €{raw_admin_cost:.2f} "
                      f"(clamped to €{min_limit:.2f} - €{max_limit:.2f})" if final_admin_cost != raw_admin_cost
                      else f"Admin costs: {percentage}% of €{base_amount:.2f} = €{raw_admin_cost:.2f}",
        'property_name': property_name
    }
