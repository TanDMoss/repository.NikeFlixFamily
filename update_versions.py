import os
import re

def get_current_version(file_path, version_pattern, group=1):
    """
    Extracts the current version from a file based on the provided regex pattern.

    Args:
        file_path (str): Path to the file.
        version_pattern (str): Regex pattern to match the version.
        group (int): The regex group number that captures the version.

    Returns:
        str: The extracted version or "Unknown" if not found.
    """
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            content = file.read()
        match = re.search(version_pattern, content)
        if match:
            return match.group(group)
    return "Unknown"

def update_version_in_addon(file_path, new_version):
    """
    Updates the version number in the addon.xml file.

    Args:
        file_path (str): Path to the addon.xml file.
        new_version (str): The new version number to set.
    """
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            lines = file.readlines()
        
        # Update the version in the second line only
        updated_lines = []
        for i, line in enumerate(lines):
            if i == 1:  # Second line (0-based index)
                # Use a lambda to avoid group reference issues
                line = re.sub(
                    r'(version=")(\d+\.\d+\.\d+)(")',
                    lambda m: f'{m.group(1)}{new_version}{m.group(3)}',
                    line
                )
            updated_lines.append(line)
        
        with open(file_path, "w") as file:
            file.writelines(updated_lines)
        print(f"Updated version in {file_path} to {new_version}.")
    else:
        print(f"{file_path} not found!")

def update_version_in_builds(file_path, version_pattern, new_version):
    """
    Updates the version number in the builds.txt file.

    Args:
        file_path (str): Path to the builds.txt file.
        version_pattern (str): Regex pattern to match the version.
        new_version (str): The new version number to set.
    """
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            content = file.read()
        # Replace all occurrences of the version pattern using a lambda
        content = re.sub(
            version_pattern,
            lambda m: f'{m.group(1)}{new_version}{m.group(3)}',
            content
        )
        with open(file_path, "w") as file:
            file.write(content)
        print(f"Updated version in {file_path} to {new_version}.")
    else:
        print(f"{file_path} not found!")

def main():
    # Paths to the files
    wizard_addon_file = "./repo/plugin.program.nikeflixwizard/addon.xml"
    wizard_builds_file = "./repo/plugin.program.nikeflixwizard/resources/text/builds.txt"

    # Patterns for matching versions
    addon_version_pattern = r'version="(\d+\.\d+\.\d+)"'  # Group 1 captures the version
    builds_version_pattern = r'(version=")(\d+\.\d+\.\d+)(")'  # Group 2 captures the version

    # Display current versions
    wizard_addon_version = get_current_version(wizard_addon_file, addon_version_pattern, group=1)
    wizard_builds_version = get_current_version(wizard_builds_file, builds_version_pattern, group=2)

    print(f"Current version in plugin.program.nikeflixwizard addon.xml: {wizard_addon_version}")
    print(f"Current version in plugin.program.nikeflixwizard builds.txt: {wizard_builds_version}")

    # Get new version from user with validation
    while True:
        new_version = input("Enter the new version number (e.g., 2.2.9): ").strip()
        if re.match(r'^\d+\.\d+\.\d+$', new_version):
            break
        else:
            print("Invalid version format. Please enter in the format X.Y.Z (e.g., 2.2.9).")

    # Update versions
    update_version_in_addon(wizard_addon_file, new_version)
    update_version_in_builds(wizard_builds_file, builds_version_pattern, new_version)

    print("All tasks completed!")

if __name__ == "__main__":
    main()
