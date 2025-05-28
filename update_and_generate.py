import os
import re
import shutil
import subprocess

def get_current_version(addon_xml_path):
    """
    Extracts the current version from the addon.xml file.
    """
    if not os.path.exists(addon_xml_path):
        print(f"{addon_xml_path} not found!")
        return None

    with open(addon_xml_path, "r") as file:
        content = file.read()

    match = re.search(r'version="(\d+\.\d+\.\d+)"', content)
    if match:
        return match.group(1)
    else:
        print("Current version not found in addon.xml.")
        return None

def update_version():
    # Paths to files
    index_html_path = "./index.html"
    addon_xml_path = "./repo/repository.NikeFlix/addon.xml"

    # Get current version
    current_version = get_current_version(addon_xml_path)
    if current_version:
        print(f"Current version: {current_version}")
    else:
        # If current version can't be determined, proceed without displaying
        pass

    # Get new version from user
    while True:
        version = input("Enter the new version number (e.g., 2.2.9): ").strip()
        if re.match(r'^\d+\.\d+\.\d+$', version):
            break
        else:
            print("Invalid version format. Please enter in the format X.Y.Z (e.g., 2.2.9).")

    # Update index.html
    if os.path.exists(index_html_path):
        with open(index_html_path, "r") as file:
            content = file.read()
        # Replace the version number in the href link
        new_content, count = re.subn(r'NikeFlix-\d+\.\d+\.\d+\.zip',
                                     f'NikeFlix-{version}.zip', content)
        if count > 0:
            with open(index_html_path, "w") as file:
                file.write(new_content)
            print(f"Updated version in {index_html_path} to {version}.")
        else:
            print(f"No version pattern found in {index_html_path}.")
    else:
        print(f"{index_html_path} not found!")

    # Update addon.xml
    if os.path.exists(addon_xml_path):
        with open(addon_xml_path, "r") as file:
            content = file.read()
        # Replace the version attribute
        new_content, count = re.subn(r'version="\d+\.\d+\.\d+"',
                                     f'version="{version}"', content)
        if count > 0:
            with open(addon_xml_path, "w") as file:
                file.write(new_content)
            print(f"Updated version in {addon_xml_path} to {version}.")
        else:
            print(f"No version attribute found in {addon_xml_path}.")
    else:
        print(f"{addon_xml_path} not found!")

    return version


def delete_zips_folder():
    zips_path = "./repo/zips"
    if os.path.exists(zips_path):
        shutil.rmtree(zips_path)
        print(f"Deleted {zips_path}.")
    else:
        print(f"{zips_path} does not exist, skipping deletion.")


def generate_repo_files():
    script_path = "./repo_generator.py"  # Path to the provided script

    if os.path.exists(script_path):
        print("Running repository generation script...")
        try:
            subprocess.run(["python", script_path], check=True)
            print("Repository generation script executed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"An error occurred while running the repository generator: {e}")
    else:
        print(f"Repository generation script {script_path} not found!")


def manage_zip_files(version):
    # Path to the zips folder
    zips_path = f"./repo/zips/repository.NikeFlix"
    main_dir = os.getcwd()

    if not os.path.exists(zips_path):
        print(f"{zips_path} not found!")
        return

    # Find the new zip file
    new_zip = f"repository.NikeFlix-{version}.zip"
    new_zip_path = os.path.join(zips_path, new_zip)

    if not os.path.exists(new_zip_path):
        print(f"Expected zip file {new_zip_path} not found!")
        return

    # Copy the new zip file to the main directory
    try:
        shutil.copy(new_zip_path, main_dir)
        print(f"Copied {new_zip} to the main directory.")
    except shutil.Error as e:
        print(f"Error copying {new_zip}: {e}")
        return

    # Delete other `repository.NikeFlix` zip files in the main directory
    deleted_files = False
    for file in os.listdir(main_dir):
        if file.startswith("repository.NikeFlix") and file.endswith(".zip") and file != new_zip:
            try:
                os.remove(os.path.join(main_dir, file))
                print(f"Deleted old zip file {file}.")
                deleted_files = True
            except OSError as e:
                print(f"Error deleting {file}: {e}")
    if not deleted_files:
        print("No old zip files to delete.")


if __name__ == "__main__":
    # Step 1: Update version numbers
    new_version = update_version()

    # Step 2: Delete the zips folder
    delete_zips_folder()

    # Step 3: Run the repository generator
    generate_repo_files()

    # Step 4: Manage zip files
    manage_zip_files(new_version)
