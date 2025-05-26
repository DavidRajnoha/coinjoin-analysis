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