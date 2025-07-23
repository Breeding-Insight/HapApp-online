#' match_alleles UI Function
#'
#' @description A shiny Module.
#'
#' @param id,input,output,session Internal parameters for {shiny}.
#'
#' @noRd
#'
#' @importFrom shiny NS tagList fluidRow column selectInput fileInput actionButton verbatimTextOutput uiOutput HTML textInput helpText icon
#' @importFrom DT dataTableOutput
mod_match_alleles_ui <- function(id) {
  ns <- NS(id)
  tagList(
    # Add custom CSS for a more compact and appealing UI
    tags$style(HTML(paste0(
      "#", ns("terminal_output"), " { color: #28a745; font-size: 0.9em; }",
      ".input-panel { padding: 20px; min-height: 680px; position: relative; padding-bottom: 90px; }",
      ".output-panel { min-height: 680px; }",
      ".form-group { margin-bottom: 15px; }",
      "label { font-weight: bold; font-size: 0.95em; }",
      ".bottom-buttons { position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%); width: 100%; text-align: center; }",
      ".species-image { max-width: 100px !important; top: 15px; right: 15px; }"
    ))),
    div(class = "title-panel",
        p("Upload your MADC file to process microhaplotype data and assign fixed allele IDs")
    ),
    fluidRow(
      # Left column for inputs
      column(
        6,
        div(
          class = "input-panel",
          div(style = "position: relative;",
              #uiOutput(ns("species_image_ui")),

              # Grouped Inputs for better organization
              strong("1. Species & Database"),
              hr(style="margin-top: 5px; margin-bottom: 15px;"),
              fluidRow(
                column(6, selectInput(ns("species"), "Species", choices = c("Select", "Alfalfa", "Strawberry", "Cranberry", "Grape", "Blueberry", "Lettuce"))),
                column(6, selectInput(ns("version_number"), "DB Version", choices = NULL))
              ),
              uiOutput(ns("species_error_message_ui")),

              strong("2. Run Parameters"),
              hr(style="margin-top: 5px; margin-bottom: 15px;"),
              fluidRow(
                column(6, selectInput(ns("design_length"), "Panel Design Length", choices = c(54, 81), selected = 81)),
                column(6, selectInput(ns("sequence_length"), "Sequence Length", choices = c(54, 81, 109), selected = 81))
              ),

              strong("3. Input File"),
              hr(style="margin-top: 5px; margin-bottom: 15px;"),
              fileInput(ns("madc_file"), "MADC File (.csv)", accept = c(".csv")),

              # Buttons at the bottom
              fluidRow(
                  actionButton(ns("run_button"), "Process Files", class = "btn-primary btn-lg btn-run", icon = icon("cogs")),
                  actionButton(ns("results_button"), "View Results", class = "btn-success btn-lg btn-run", icon = icon("folder-open"))
              )
          )
        )
      ),
      # Right column for output
      column(
        6,
        div(
          class = "output-panel",
          h4("Terminal Output:"),
          verbatimTextOutput(ns("terminal_output"), placeholder = TRUE)
        )
      )
    ),
    # MADC Preview Panel
    div(
      class = "preview-panel",
      h4("MADC File Preview"),
      DT::dataTableOutput(ns("madc_preview"))
    )
  )
}

#' match_alleles Server Functions
#'
#' @import shiny
#' @import golem
#' @importFrom magrittr %>%
#' @importFrom DT renderDataTable
#' @importFrom tools file_path_sans_ext
#' @importFrom fs dir_create file_exists path_abs path path_home
#' @importFrom utils read.csv zip
#' @importFrom processx run
#'
#' @noRd
mod_match_alleles_server <- function(id) {
  moduleServer(id, function(input, output, session) {
    ns <- session$ns

    # --- Setup a session-specific temporary directory ---
    # This directory will be automatically cleaned up when the session ends.
    tmp_dir <- file.path(tempdir(), session$token)
    fs::dir_create(tmp_dir)

    # --- Reactive values ---
    rv <- reactiveValues(
      process_log = "Welcome! Please select your options and click 'Process Files'.",
      readme_path = NULL,
      process_running = FALSE
    )

    # --- Helper function for checking dependencies ---
    check_dependencies <- function() {
      missing <- c()

      # Check for command-line tools by checking the system PATH
      if (Sys.which("python3") == "") {
        missing <- c(missing, "Python 3")
      }
      if (Sys.which("cutadapt") == "") {
        missing <- c(missing, "cutadapt")
      }
      if (Sys.which("blastn") == "") {
        missing <- c(missing, "blastn (from NCBI BLAST+ suite)")
      }

      # Note: We are no longer checking for python modules like pandas here,
      # as it is unreliable across different user environments (e.g. conda).
      # If a module is missing, the error will appear in the terminal output.

      return(missing)
    }


    # --- UI Outputs ---

    # Render species image
    output$species_image_ui <- renderUI({
      req(input$species, input$species != "Select")
      img_path <- app_sys(paste0("app/www/images/", tolower(input$species), ".jpg"))

      if (fs::file_exists(img_path)) {
        img_src <- paste0("www/images/", tolower(input$species), ".jpg")
      } else {
        img_src <- "www/images/placeholder.jpg"
      }

      tags$img(src = img_src, alt = input$species, class = "species-image")
    })

    # --- Observers and Reactivity ---

    # Update Allele DB version dropdown based on selected species
    observeEvent(input$species, {
      req(input$species, input$species != "Select")

      output$species_error_message_ui <- renderUI(NULL)
      updateSelectInput(session, "version_number", choices = character(0))

      base_path <- app_sys("database")
      species_path <- fs::path(base_path, input$species)

      if (!fs::dir_exists(species_path)) {
        output$species_error_message_ui <- renderUI({
          div(style = "color: red;", paste0("mHap directory for '", input$species, "' does not exist."))
        })
        return()
      }

      subdirs <- list.dirs(species_path, full.names = TRUE, recursive = FALSE)
      if (length(subdirs) != 1) {
        output$species_error_message_ui <- renderUI({
          div(style = "color: red;", paste("Expected one subdirectory in", species_path, ", but found", length(subdirs)))
        })
        return()
      }

      data_dir <- fs::path(subdirs[1], "data")
      if (!fs::dir_exists(data_dir)) {
        output$species_error_message_ui <- renderUI({
          div(style = "color: red;", paste("'data' directory not found in", data_dir))
        })
        return()
      }

      fa_files <- list.files(data_dir, pattern = "\\.fa$", full.names = FALSE)
      if (length(fa_files) == 0) {
        output$species_error_message_ui <- renderUI({
          div(style = "color: red;", paste("No .fa files found in", data_dir))
        })
        return()
      }

      fa_names <- sort(tools::file_path_sans_ext(fa_files), decreasing = TRUE)
      updateSelectInput(session, "version_number", choices = fa_names)
    })

    # Render MADC file preview
    output$madc_preview <- DT::renderDataTable({
      req(input$madc_file)
      tryCatch({
        df <- read.csv(input$madc_file$datapath, nrows = 50)
        DT::datatable(df, options = list(scrollX = TRUE, pageLength = 5, lengthMenu = c(5, 10, 25, 50)), rownames = FALSE)
      }, error = function(e) {
        showNotification(paste("Error reading MADC file:", e$message), type = "error")
        return(NULL)
      })
    })

    # --- Process Execution ---
    observeEvent(input$run_button, {
      # --- Dependency Check ---
      missing_deps <- check_dependencies()
      if (length(missing_deps) > 0) {
        showModal(modalDialog(
          title = "Missing Dependencies",
          p("The following required tools could not be found on your system:"),
          tags$ul(lapply(missing_deps, function(x) tags$li(strong(x)))),
          hr(),
          p("Please install them and ensure they are available in your system's PATH before running the application."),
          easyClose = TRUE, footer = modalButton("Dismiss")
        ))
        return()
      }

      # --- Input Validation ---
      if (is.null(input$madc_file) || input$species == "Select" || is.null(input$version_number) || input$version_number == "") {
        showModal(modalDialog(
          title = "Missing Inputs",
          "Please ensure you have selected a species, a DB version, and uploaded a MADC file.",
          easyClose = TRUE, footer = NULL
        ))
        return()
      }

      # --- End Validation ---

      rv$process_running <- TRUE
      rv$process_log <- "Starting process... This may take a few moments."

      script_path <- app_sys("bash", "20250221-build_sweetpotato_madc_DSp24-9714_as_edits.bash")
      Sys.chmod(script_path, "0755")

      # Use the session-specific temp directory for the uploaded file
      tmp_madc_path <- file.path(tmp_dir, input$madc_file$name)
      file.copy(input$madc_file$datapath, tmp_madc_path, overwrite = TRUE)

      python_scripts_dir <- app_sys("python")

      args <- c(
        python_scripts_dir,
        tmp_dir, # Pass the temp dir to the script
        input$species,
        input$version_number,
        tmp_madc_path, # Use the temp path for the script argument
        input$madc_file$name,
        input$design_length,
        input$sequence_length
      )

      tryCatch({
        processx::run(
          command = script_path,
          args = args,
          wd = app_sys()
        )
        rv$process_log <- paste0(rv$process_log, "\n\n###### Process Complete! #######\nClick 'View Results' to download your files.")
      }, error = function(e) {
        rv$process_log <- paste0(rv$process_log, "\n\nERROR: Process failed.\n", e$message)
        showNotification("The process failed. Check the terminal output for details.", type = "error", duration = 10)
      })

      rv$process_running <- FALSE
    })

    # --- Terminal Output Display ---
    poller <- reactivePoll(1000, session,
                           checkFunc = function() {
                             readme_file <- list.files(tmp_dir, pattern = "_process\\.readme$", full.names = TRUE)
                             if (length(readme_file) > 0) {
                               rv$readme_path <- readme_file[1]
                               file.info(rv$readme_path)$mtime[1]
                             } else {
                               rv$process_running
                             }
                           },
                           valueFunc = function() {
                             if (!is.null(rv$readme_path) && fs::file_exists(rv$readme_path)) {
                               readLines(rv$readme_path) %>% paste(collapse = "\n")
                             } else {
                               rv$process_log
                             }
                           }
    )

    output$terminal_output <- renderText({
      poller()
    })


    # --- Results Viewer and Download ---
    observeEvent(input$results_button, {
      output_files <- list.files(tmp_dir, full.names = FALSE)

      if (length(output_files) == 0) {
        showModal(modalDialog(title = "No Results", "No output files found yet. Please run the process first.", easyClose = TRUE))
        return()
      }

      core_pattern <- "_snpID_rename_updatedSeq.csv$|_snpID_rename.csv$|_v.*\\.csv$|\\.readme$|_v.*\\.fa$|_matchCnt_lut.txt$"
      core_files <- grep(core_pattern, output_files, value = TRUE)
      diagnostic_files <- setdiff(output_files, core_files)

      showModal(modalDialog(
        title = "Processed Files",
        size = "l",
        p("Select files to include in the ZIP archive."),
        fluidRow(
          column(6,
                 h4("Core Files"),
                 checkboxGroupInput(ns("core_files_dl"), "", choices = core_files, selected = core_files)
          ),
          column(6,
                 h4("Diagnostic Files"),
                 checkboxGroupInput(ns("diag_files_dl"), "", choices = diagnostic_files)
          )
        ),
        footer = tagList(
          modalButton("Cancel"),
          downloadButton(ns("download_zip"), "Download Selected")
        )
      ))
    })

    output$download_zip <- downloadHandler(
      filename = function() {
        paste0("MADC_matchAlleles_results_", format(Sys.time(), "%Y%m%d-%H%M"), ".zip")
      },
      content = function(file) {
        selected <- c(input$core_files_dl, input$diag_files_dl)
        req(length(selected) > 0)

        # Get full paths of selected files from the temp directory
        files_to_zip <- fs::path(tmp_dir, selected)
        zip::zip(zipfile = file, files = files_to_zip, mode = "cherry-pick")
      },
      contentType = "application/zip"
    )

  })
}
