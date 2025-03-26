from shiny import App, render, ui, reactive
from shiny.ui import page_navbar
from functools import partial
import subprocess
import sys
import shutil
import os
import pandas as pd
import glob
import fnmatch
from shiny.ui import output_data_frame

app_ui = ui.page_navbar(
    ui.nav_panel("Module1a",
            # Add custom CSS
        ui.tags.style(
            """
            body {
                background-color: #707070;
            }
            .title-panel {
                background-color: #f8f0ff;
                padding: 20px;
                border-radius: 5px;
                margin-bottom: 20px;
            }
            .note-panel {
                background-color: #d7fdeb;
                padding: 20px;
                border-radius: 5px;
                margin-bottom: 20px;
            }
            .input-panel {
                background-color: white;
                padding: 20px;
                height: 700px;
                border-radius: 5px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            .btn-run {
                margin-top: 20px;
            }
            .btn-github {
                margin-top: 20px;
            }
            .output-panel {
                background-color: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                height: 700px;
                overflow-y: auto;
                font-family: monospace;
            }
            .preview-panel {
                background-color: white;
                padding: 15px;
                border-radius: 5px;
                margin-top: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
            .dataTable {
                width: 100% !important;
                margin-top: 10px !important;
            }
            .dataTables_wrapper {
                padding: 10px;
            }
            /* Add custom CSS for positioning the image */
            .species-image {
                position: absolute;
                top: 20px;
                right: 20px;
                border-radius: 5px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                max-width: 150px !important;
                width: 100% !important;
                height: auto !important;
            }
            """
        ),

        ui.tags.script(
            """
            Shiny.addCustomMessageHandler('show_modal', function(message) {
                $('#' + message.id).modal('show');
            });

            Shiny.addCustomMessageHandler('hide_modal', function(message) {
                $('#' + message.id).modal('hide');
            });
            """
        ),
        
        # Title Panel
        ui.div(
            {"class": "title-panel"},
            #ui.h2("Microhaplotype Database Tool", {"style": "color: #2c3e50;"}),
            ui.p("Upload your MADC file to process microhaplotype data and assign fixed allele IDs", {"style": "color: #7f8c8d;"})
        ),

        #Tabs for the matchAlleles and refAlt_db
        ui.navset_card_underline(
            ui.nav_panel("matchAlleles",
                # Main content in two columns
                ui.row(
                    # Left column for inputs
                    ui.column(
                        6,
                        ui.div(
                            {"class": "input-panel"},
                            #Species dropdown and image
                            ui.div(
                                {"style": "position: relative;"},
                                # Species dropdown
                                ui.div(
                                    {"class": "mb-4"},
                                    ui.h4("Select Species"),
                                    ui.input_select(
                                        "species",
                                        "",
                                        choices=[
                                            "Select",
                                            "Alfalfa",
                                            "Strawberry",
                                            "Cranberry",
                                            "Grape",
                                            "Blueberry",
                                            "Lettuce"
                                        ]
                                    )
                                ),
                                # Error message output
                                ui.output_text(
                                    "species_error_message",
                                    inline=True,
                                    container=partial(ui.div, style="color: red;"),
                                ),
                                # Image placeholder
                                ui.output_ui(
                                    "species_image"
                                ),
                            ),
                            # Allele DB Version dropdown
                            ui.div(
                                {"class": "mb-4"},
                                ui.h4("Allele DB Version"),
                                ui.input_select(
                                    "version_number",
                                    "",
                                    choices=[],  # Initially empty; will be populated dynamically
                                ),
                            ),
                            # Panel design length dropdown
                            ui.div(
                                {"class": "mb-4"},
                                ui.h4("Panel Design Length"),
                                ui.input_select(
                                    "design_length",
                                    "",
                                    choices=[54,81],  # check what options are available
                                ),
                            ),
                            # Sequence length dropdown
                            ui.div(
                                {"class": "mb-4"},
                                ui.h4("Sequence Length"),
                                ui.input_select(
                                    "sequence_length",
                                    "",
                                    choices=[54,81,109],  # Check what options are available
                                ),
                            ),
                            ui.div(
                                {"class": "mb-3"},
                                ui.h4("MADC File"),
                                ui.input_file("file3", "", accept=None)
                            ),
                            
                            # Run button
                            ui.div(
                                {"class": "text-center"},
                                ui.input_action_button(
                                    "run_button", 
                                    "Process Files",
                                    class_="btn-primary btn-lg btn-run"
                                )
                            ),
                            #Results button
                            ui.div(
                                {"class": "text-center"},
                                ui.input_action_button(
                                    "results_button", 
                                    "View Results",
                                    class_="btn-success btn-lg btn-run"
                                )
                            ),
                        ),
                    ),
                    
                    # Right column for output
                    ui.column(
                        6,
                        ui.div(
                            {"class": "output-panel"},
                            ui.h4("Terminal Output:"),
                            ui.output_text_verbatim("terminal_output")
                        )
                    )
                ),
                
                # MADC Preview Panel - Full width below
                ui.div(
                    {"class": "preview-panel"},
                    ui.h4("MADC File Preview"),
                    output_data_frame("madc_preview")
                )
            ),
            ui.nav_panel(
                "UpdateDB", 
                # Main content in two columns
                ui.row(
                    # Left column for inputs
                    ui.column(
                        6,
                        ui.div(
                            {"class": "input-panel"},
                            #Species dropdown and image
                            ui.div(
                                {"class": "note-panel"},
                                ui.p("Download mHap database updates from GitHub", {"style": "color: #7f8c8d;"})
                            ),
                            ui.div(
                                {"style": "position: relative;"},
                                # GitHub Species Selection
                                ui.div(
                                    {"class": "mb-4"},
                                    ui.h4("Select Species"),
                                    ui.input_select(
                                        "github_species",
                                        "",
                                        choices=[
                                            "Select",
                                            "Alfalfa",
                                            "Blueberry",
                                            "Cranberry",
                                            "Cucumber",
                                            "Lettuce"
                                        ]
                                    )
                                ),
                                # Success message output
                                ui.output_text(
                                    "success_message_output",
                                    inline=True,
                                    container=partial(ui.div, style="color: green;"),
                                ),
                            ),
                            # Run button
                            ui.div(
                                {"class": "text-center"},
                                ui.input_action_button(
                                    "github_button", 
                                    "Sync from Github",
                                    class_="btn-danger btn-lg btn-github"
                                )
                            )
                        ),
                    ),
                    
                    # Right column for output
                    ui.column(
                        6,
                        ui.div(
                            {"class": "output-panel"},
                            ui.h4("Terminal Output:"),
                            ui.output_text_verbatim("github_output")
                        )
                    )
                ),
            )
        )
    ),  
    ui.nav_panel(
        "Module1b",
        ui.div(
            {"class": "title-panel"},
            #ui.h2("Microhaplotype Database Tool", {"style": "color: #2c3e50;"}),
            ui.p("Upload your MADC file to assign fixed allele IDs. This module does not generate a mHap database file.", {"style": "color: #7f8c8d;"})
        ),
        ui.navset_card_underline(
                ui.nav_panel("Tab 1", "Tab 1 content"),
                ui.nav_panel("Tab 2", "Tab 2 content"),
                ui.nav_panel("Tab 3", "Tab 3 content"),
        )
    ),  
    ui.nav_panel("Help", "Page C content"),  
    title="MADC FixedAlleleID Tool",  
    id="page",
    theme=ui.Theme("flatly") 
)  

def server(input, output, session):
    from shiny import req, reactive, ui
    import os
    import glob
    import secrets
    import zipfile
    from datetime import datetime


    #Results window
    refresh_trigger = reactive.Value(0)

    def categorize_files(files):
        core_files = []
        diagnostic_files = []

        for file in files:
            if (
                file.endswith("_snpID_rename_updatedSeq.csv")
                or file.endswith("_snpID_rename.csv")
                or fnmatch.fnmatch(file, "*_v*.csv")
                or file.endswith(".readme")
                or "_v" in file and file.endswith(".fa")
                or file.endswith("_matchCnt_lut.txt")
            ):
                core_files.append(file)
            elif "_v" not in file:
                diagnostic_files.append(file)

        return sorted(core_files, reverse=True), sorted(diagnostic_files, reverse=True)

    @output
    @render.ui
    def file_list():
        # Depend on refresh_trigger to refresh file list
        refresh_trigger.get()

        tmp_dir = "tmp"
        if not os.path.exists(tmp_dir):
            return ui.div("No files found in the tmp directory.")

        files = os.listdir(tmp_dir)
        if not files:
            return ui.div("No files found in the tmp directory.")

        # Categorize files
        core_files, diagnostic_files = categorize_files(files)

        # Generate checkboxes for each category
        core_checkboxes = [ui.input_checkbox(f"core_file_{i}", file, value=True) for i, file in enumerate(core_files)]
        diagnostic_checkboxes = [ui.input_checkbox(f"diag_file_{i}", file) for i, file in enumerate(diagnostic_files)]

        # Create collapsible section for diagnostics
        diagnostic_section = ui.div(
            ui.tags.button(
                "Toggle Diagnostic Files",
                class_="btn btn-secondary",
                type="button",
                **{"data-bs-toggle": "collapse", "data-bs-target": "#diagnostics-section"}
            ),
            ui.div(
                *diagnostic_checkboxes,
                id="diagnostics-section",
                class_="collapse mt-3"  # Adds collapse functionality and margin for spacing
            ),
        )

        # Arrange UI components
        return ui.div(
            ui.row(
                ui.column(6, ui.h4("Core Files"), ui.div(*core_checkboxes)),
                ui.column(6, ui.h4("Diagnostic Files"), diagnostic_section),
            )
        )

    @reactive.Calc
    def selected_files():
        tmp_dir = "tmp"
        files = os.listdir(tmp_dir)
        core_files, diagnostic_files = categorize_files(files)

        selected_core = [
            os.path.join(tmp_dir, file)
            for i, file in enumerate(core_files)
            if getattr(input, f"core_file_{i}")()
        ]
        selected_diag = [
            os.path.join(tmp_dir, file)
            for i, file in enumerate(diagnostic_files)
            if getattr(input, f"diag_file_{i}")()
        ]

        return selected_core + selected_diag

    @reactive.effect
    @reactive.event(input.results_button)
    def _():
        # Increment the refresh trigger to force file list refresh
        refresh_trigger.set(refresh_trigger.get() + 1)

        k = ui.modal(
            ui.div(
                ui.p("Please select the files you would like to download."),
                ui.output_ui("file_list"),
                ui.div(
                    ui.download_button("download_zip", "Download", class_="btn-warning")
                )
            ),
            title="Processed Files",
            easy_close=True,
            footer=ui.modal_button("Close", id="close_results_modal"),
            size="xl"
        )
        ui.modal_show(k)

    @render.download(
        filename=lambda: f"MADC_matchAlleles_selected_files_{datetime.now().strftime('%Y%m%d-%H.%M')}.zip"
    )
    def download_zip():
        tmp_dir = "tmp"
        zip_file_path = os.path.join(tmp_dir, "selected_files.zip")

        # Create the ZIP file dynamically
        selected = selected_files()
        if not selected:
            raise ValueError("No files selected for download.")

        try:
            with zipfile.ZipFile(zip_file_path, 'w') as zipf:
                for file_path in selected:
                    zipf.write(file_path, os.path.basename(file_path))
            print(f"ZIP file created: {zip_file_path}")
        except Exception as e:
            raise ValueError(f"Error creating ZIP file: {e}")

        # Serve the ZIP file for download
        return zip_file_path

    #Github window
    # Reactive value to hold success messages
    success_message = reactive.Value("")

    @reactive.effect
    @reactive.event(input.github_button)
    def _():

        success_message.set("")  # Clear previous error message

        m = ui.modal(
            ui.div(
                ui.p("Please enter your GitHub credentials to sync the database."),
                ui.div(
                    ui.h4("User ID"),
                    ui.input_text("github_user_id", "", placeholder="username")
                ),
                ui.div(
                    ui.h4("GitHub Token PAT"),
                    ui.input_password("github_token_pat", "", placeholder="token")
                ),
                ui.div(
                    ui.input_action_button("sync_button", "Sync", class_="btn-primary")
                )
            ),
            title="GitHub Sync",
            easy_close=True,
            footer=ui.modal_button("Close", id="close_github_modal")
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.sync_button)
    def _():
        # Simulate the sync process
        # Here you would add the actual sync logic
        success_message.set("Success!")

        ui.modal_remove()

    @output
    @render.text
    def success_message_output():
        return success_message.get()
    
    @output
    @render.text
    async def github_output():
        if input.github_button() == 0 or input.sync_button() == 0:
            return "Click 'Sync from Github' to retrieve the species database..."
        if input.sync_button() != 0 and input.github_button != 0:
            return "Microhaplotype database download...Complete!"

        if not all([input.file1(), input.file2(), input.file3()]):
            return "Please upload all required files"

    # Path to the images directory
    image_dir = os.path.join(os.path.dirname(__file__), "www", "images")

    # Reactive value to hold error messages
    error_message = reactive.Value("")

    @output
    @render.text
    def species_error_message():
        return error_message.get()
    
    @output
    @render.ui
    def species_image():
        from shiny import req
        import os

        # Path to the images directory
        image_dir = os.path.join(os.path.dirname(__file__), "www", "images")

        # Ensure a species is selected
        species = input.species()
        req(species)  # Wait until a species is selected

        # Map species names to image filenames
        image_filename = f"{species}.jpg"

        # Full path to the image file
        image_path = os.path.join(image_dir, image_filename)

        # Check if the image file exists
        if not os.path.exists(image_path):
            # Use placeholder image
            image_src = "images/placeholder.jpg"
        else:
            # Since images are in www/images/, use the relative path
            image_src = f"images/{image_filename}"

        # Return an img tag with the correct src and class
        return ui.img(
            {
                "src": image_src,
                "alt": species,
                "class": "species-image",
                # You can also add inline styles if needed
                # "style": "max-width: 150px; width: 100%; height: auto;",
            }
        )

    @reactive.Effect
    def _update_version_number():
        species = input.species()
        req(species and species != "Select")

        error_message.set("")  # Clear previous error message

        # Path to 'database/{species}'
        species_dir = os.path.join(os.path.dirname(__file__), 'database', species)

        if not os.path.exists(species_dir):
            # Set error message
            error_message.set(f"mHap directory for '{species}' does not exist.")
            # Clear the options in 'version_number'
            session.send_input_message("version_number", {"options": []})
            return

        # List subdirectories in species_dir
        subdirs = [
            d for d in os.listdir(species_dir)
            if os.path.isdir(os.path.join(species_dir, d))
        ]

        if len(subdirs) != 1:
            # Set error message
            error_message.set(
                f"Expected one subdirectory in '{species_dir}', found {len(subdirs)}."
            )
            # Clear the options in 'version_number'
            session.send_input_message("version_number", {"options": []})
            return

        # There is exactly one subdirectory
        version_dir = os.path.join(species_dir, subdirs[0])

        # Path to 'data' directory inside version_dir
        data_dir = os.path.join(version_dir, 'data')

        if not os.path.exists(data_dir):
            # Set error message
            error_message.set(f"'data' directory not found in '{version_dir}'.")
            # Clear the options in 'version_number'
            session.send_input_message("version_number", {"options": []})
            return

        # Get list of .fa files in data_dir
        fa_files = glob.glob(os.path.join(data_dir, '*.fa'))

        if not fa_files:
            # Set error message
            error_message.set(f"No .fa files found in '{data_dir}'.")
            # Clear the options in 'version_number'
            session.send_input_message("version_number", {"options": []})
            return

        # Get filenames without .fa extension
        fa_names = [os.path.splitext(os.path.basename(f))[0] for f in fa_files]
        fa_names = sorted(fa_names, reverse=True)
        print()
        # Prepare options as list of dictionaries
        options = [{"label": name, "value": name} for name in fa_names]

        # Update 'version_number' options
        ui.update_select(
            "version_number",
            choices=fa_names,
            )

        # Clear error message
        error_message.set("")


    @output
    @render.data_frame
    def madc_preview():
        if not input.file3():
            # Return an empty DataFrame if no file is uploaded
            return pd.DataFrame({"Message": ["No file uploaded yet."]})

        try:
            # Load the file and read the first 100 rows
            file_path = input.file3()[0]['datapath']
            df = pd.read_csv(file_path, nrows=50)

            # Return the DataFrame for rendering as a table
            return df

        except Exception as e:
            # Return an error DataFrame if file processing fails
            return pd.DataFrame({"Error": [str(e)]})

    #Processing MADC
    def find_readme_file(tmp_dir="tmp"):
        # Search for the .readme file in the tmp directory
        files = glob.glob(os.path.join(tmp_dir, "*_process.readme"))
        if files:
            return files[0]  # Return the first match
        return None

    @output
    @render.text
    async def terminal_output():
        if input.run_button() == 0:
            return "Click 'Process Files' to execute your scripts..."

        if not all([input.file3()]):
            return "Please upload all required files"
        
        # Locate the .readme file
        if input.run_button() != 0:
            readme_file = find_readme_file()
            if not readme_file:
                return "Processing... Please wait or check for errors."
        
        #Species variable
        species = input.species()

        #Haplotype DB version
        db_version = input.version_number()

        # Get file info - note that we need to access the first item in the list
        #file1_info = input.file1()[0]  # input.file1() returns a list of dictionaries
        #file2_info = input.file2()[0]
        file3_info = input.file3()[0]

        # Get paths and original names
        #file1_path = file1_info['datapath']
        #file2_path = file2_info['datapath']
        file3_path = file3_info['datapath']

        # Make sure to get the original names
        #file1_original_name = file1_info['name']  # This gets the actual uploaded filename
        #file2_original_name = file2_info['name']
        file3_original_name = file3_info['name']

        # Get original paths (directory paths)
        #file1_original_dir = os.path.dirname(os.path.abspath(file1_info['name']))
        #file2_original_dir = os.path.dirname(os.path.abspath(file2_info['name']))
        #file3_original_dir = os.path.dirname(os.path.abspath(file3_info['name']))

        #Sequence length
        des_len = input.design_length()

        #Design length
        seq_len = input.sequence_length()

        # Get base directory
        #base_dir = os.path.abspath(os.path.dirname(__file__))

        # Define the complete path to the data directory
        #data_dir = os.path.join(base_dir, "MicrohaplotypeDB_Module1a/alfalfa_haplotype_db-master/data")

        # Print debug information
        print(f"Species: {species}", flush=True)
        print(f"db version: {db_version}")
        print(f"MADC directory path: {file3_path}")
        print(f"MADC original name: {file3_original_name}")


        # Command to run the bash script with quoted arguments
        #command = f"""bash MicrohaplotypeDB_Module1a/matchAlleles/build54bp_02_matchHaps_20241118.bash '{file1_path}' '{file2_path}' '{file3_path}' '{file1_original_name}' '{file2_original_name}' '{file3_original_name}'"""
        command = f"""bash MicrohaplotypeDB_Module1a/matchAlleles/20250221-build_sweetpotato_madc_DSp24-9714_as_edits.bash {species} {db_version} {file3_path} {file3_original_name} {des_len} {seq_len}"""
        
        # In your Shiny app, before executing the command:
        print("Current working directory:", os.getcwd())
        print("Executing command:", command)

        # Execute the command and capture the output
        try:
            process = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=True
            )

            output_text = process.stdout

        except subprocess.CalledProcessError as e:
            output.output_files_ui.set(render.ui(ui.div(f"Error executing script: {e.stderr}")))
        except Exception as e:
            output.output_files_ui.set(render.ui(ui.div(f"Unexpected error: {str(e)}")))

        # Locate and read the .readme file
        readme_file = find_readme_file()
        if not readme_file:
            return "Processing completed, but no .readme file found in the tmp directory."

        try:
            with open(readme_file, "r") as file:
                return file.read()
        except Exception as e:
            return f"Error reading .readme file: {e}"

    ##Get updated DB from GitHub
    # Define species to repository URL mapping
    species_repo_urls = {
        'Alfalfa': 'https://github.com/Breeding-Insight/alfalfa_haplotype_db.git',
        'Cranberry': 'https://github.com/Breeding-Insight/cranberry_haplotype_db.git',
        'Cucumber': 'https://github.com/Breeding-Insight/Cucumber_haplotype_db.git',
        'Lettuce': 'https://github.com/Breeding-Insight/Lettuce_haplotype_db.git',
        'Blueberry': 'https://github.com/Breeding-Insight/blueberry_haplotype_db.git',
    }


    @output
    @render.text
    async def output_files():
        # Example placeholders for output paths
        output_file1 = "/path/to/output1.txt"
        output_file2 = "/path/to/output2.txt"
        
        if os.path.exists(output_file1) and os.path.exists(output_file2):
            return f"Output files generated:\n{output_file1}\n{output_file2}"
        else:
            return "Output files have not been generated yet."

# Create the application
app = App(
    app_ui,
    server,
    static_assets={
        '/images': os.path.join(os.path.dirname(__file__), 'www', 'images')
    }
)

# Run this script with `shiny run filename.py`