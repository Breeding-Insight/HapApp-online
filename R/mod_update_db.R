#' update_db UI Function
#'
#' @description A shiny Module.
#'
#' @param id,input,output,session Internal parameters for {shiny}.
#'
#' @noRd
#'
#' @importFrom shiny NS tagList
mod_update_db_ui <- function(id){
  ns <- NS(id)
  tagList(
    div(class = "note-panel",
        p("This module allows you to sync the microhaplotype database from GitHub.")
    ),
    fluidRow(
      column(6,
             div(class = "input-panel",
                 h4("Select Species to Update"),
                 selectInput(ns("github_species"), "", choices = c("Select", "Alfalfa", "Blueberry", "Cranberry", "Cucumber", "Lettuce")),
                 uiOutput(ns("sync_message_ui")),
                 div(class="text-center",
                     actionButton(ns("github_button"), "Sync from Github", class="btn-danger btn-lg btn-github")
                 )
             )
      ),
      column(6,
             div(class = "output-panel",
                 h4("Terminal Output:"),
                 verbatimTextOutput(ns("github_output"), placeholder = TRUE)
             )
      )
    )
  )
}

#' update_db Server Functions
#'
#' @noRd
mod_update_db_server <- function(id){
  moduleServer( id, function(input, output, session){
    ns <- session$ns

    rv_git <- reactiveValues(log = "Ready to sync from GitHub...")

    observeEvent(input$github_button, {
      req(input$github_species != "Select")

      showModal(modalDialog(
        title = "GitHub Sync",
        "This will attempt to clone or update the database from GitHub.",
        textInput(ns("github_user"), "GitHub User (optional)"),
        passwordInput(ns("github_pat"), "GitHub PAT (optional, for private repos)"),
        footer = tagList(
          modalButton("Cancel"),
          actionButton(ns("sync_button"), "Confirm Sync")
        )
      ))
    })

    observeEvent(input$sync_button, {
      removeModal()

      species_repo_map <- c(
        'Alfalfa' = 'https://github.com/Breeding-Insight/alfalfa_haplotype_db.git',
        'Cranberry' = 'https://github.com/Breeding-Insight/cranberry_haplotype_db.git',
        'Cucumber' = 'https://github.com/Breeding-Insight/Cucumber_haplotype_db.git',
        'Lettuce' = 'https://github.com/Breeding-Insight/Lettuce_haplotype_db.git',
        'Blueberry' = 'https://github.com/Breeding-Insight/blueberry_haplotype_db.git'
      )

      repo_url <- species_repo_map[input$github_species]
      target_dir <- app_sys("database", input$github_species)

      rv_git$log <- paste("Syncing", input$github_species, "from", repo_url, "...")

      # Simple git clone/pull logic
      if (fs::dir_exists(target_dir)) {
        # It exists, so pull
        cmd <- "git"
        args <- c("-C", target_dir, "pull")
        rv_git$log <- paste(rv_git$log, "\nDirectory exists. Attempting to pull updates...")
      } else {
        # It doesn't exist, so clone
        cmd <- "git"
        args <- c("clone", repo_url, target_dir)
        rv_git$log <- paste(rv_git$log, "\nDirectory does not exist. Attempting to clone...")
      }

      # Run process
      processx::run(
        command = cmd,
        args = args,
        error_on_status = FALSE,
        stdout_line_callback = function(line, proc) {
          rv_git$log <- paste0(rv_git$log, line, "\n")
        },
        stderr_line_callback = function(line, proc) {
          rv_git$log <- paste0(rv_git$log, "ERROR: ", line, "\n")
        }
      )$finally(function(){
        rv_git$log <- paste0(rv_git$log, "\n\nSync complete.")
      })
    })

    output$github_output <- renderText({
      rv_git$log
    })

  })
}
