import json
import os

def parse_client_roles_from_scenario(scenario: dict) -> dict[str, str]:
    """
    Extracts a mapping of client_id to role ('maker' or 'taker')
    from the scenario structure.
    Expects scenario to be a dict loaded from JSON/YAML.
    """
    client_roles = {}
    for n, wallet in enumerate(scenario.get('wallets', [])):
        id = f"jcs-{n:03}"
        role = wallet.get('type')
        if id and role:
            client_roles[id] = role
    return client_roles


def parse_client_fidelity_bonds_from_scenario(scenario: dict) -> dict[str, dict]:
    """
    Extracts fidelity bond information for each client from the scenario.

    Args:
        scenario: Scenario dict loaded from JSON, expected to contain 'wallets' key

    Returns:
        Dictionary mapping client_id to fidelity bond info:
        {
            "jcs-000": {"enabled": True, "amount": 65598, "locktime": "2026-10"},
            "jcs-001": {"enabled": False, "amount": None, "locktime": None},
            ...
        }
        Returns empty dict if no fidelity bond information is present.
    """
    client_bonds = {}

    for n, wallet in enumerate(scenario.get('wallets', [])):
        client_id = f"jcs-{n:03}"

        # Extract fidelity bond info if present
        fb_info = wallet.get('fidelity_bond', {})

        if fb_info and fb_info.get('enabled', False):
            client_bonds[client_id] = {
                'enabled': True,
                'amount': fb_info.get('amount'),
                'locktime': fb_info.get('locktime')
            }
        else:
            # No fidelity bond or explicitly disabled
            client_bonds[client_id] = {
                'enabled': False,
                'amount': None,
                'locktime': None
            }

    return client_bonds

def load_client_roles_from_file(project_root: str = None) -> dict[str, str]:
    """
    Loads scenario.json from the top-level directory and returns {client_id: role} mapping.
    If project_root is None, uses the parent of this file's parent (i.e., repo root).
    Returns an empty dict if the scenario file doesn't exist.
    """
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Try in the project root
    scenario_path = os.path.join(project_root, 'scenario.json')

    # If not found, try in subdirectories
    if not os.path.exists(scenario_path):
        print(f"Warning: scenario.json not found at {scenario_path}, looking in subdirectories...")
        # Check if it's in a data directory
        scenario_path = os.path.join(project_root, 'data', 'scenario.json')

    # If still not found, return empty dict
    if not os.path.exists(scenario_path):
        print(f"Warning: scenario.json not found, proceeding without client roles")
        return {}

    try:
        with open(scenario_path, 'r') as f:
            scenario = json.load(f)
        print(f"Loaded client roles from {scenario_path}")
        return parse_client_roles_from_scenario(scenario)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading scenario.json: {e}")
        return {}


def identify_sole_takers(run_path: str) -> set[str]:
    """
    Identify sole takers: clients without TUMBLE.log and without yigen-statement.csv.

    Sole takers are standard takers that are:
    - NOT tumblers (no TUMBLE.log in logs/)
    - NOT makers (no yigen-statement.csv in logs/)

    Args:
        run_path: Path to the run directory containing data/ subdirectory with client folders

    Returns:
        Set of client IDs that are sole takers (e.g., {'jcs-000', 'jcs-001', ...})
        Returns empty set if data directory doesn't exist or has issues.
    """
    sole_takers = set()

    # Construct path to data directory
    data_path = os.path.join(run_path, 'data')

    if not os.path.exists(data_path):
        print(f"Warning: data directory not found at {data_path}")
        return sole_takers

    try:
        # Iterate through all client directories
        for entry in os.listdir(data_path):
            client_dir = os.path.join(data_path, entry)

            # Skip if not a directory or doesn't match client pattern
            if not os.path.isdir(client_dir) or not entry.startswith('jcs-'):
                continue

            logs_dir = os.path.join(client_dir, 'logs')

            # Skip if logs directory doesn't exist
            if not os.path.exists(logs_dir):
                continue

            # Check for tumbler indicator (TUMBLE.log)
            has_tumble_log = os.path.exists(os.path.join(logs_dir, 'TUMBLE.log'))

            # Check for maker indicator (yigen-statement.csv)
            has_yigen_statement = os.path.exists(os.path.join(logs_dir, 'yigen-statement.csv'))

            # Add to sole takers if neither file exists
            if not has_tumble_log and not has_yigen_statement:
                sole_takers.add(entry)

        if sole_takers:
            print(f"Identified {len(sole_takers)} sole taker(s): {sorted(sole_takers)}")
        else:
            print("No sole takers identified in this dataset")

    except Exception as e:
        print(f"Error identifying sole takers: {e}")

    return sole_takers