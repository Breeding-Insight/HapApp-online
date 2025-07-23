#' The application User-Interface
#'
#' @param request Internal parameter for `{shiny}`.
#'     DO NOT REMOVE.
#' @import shiny
#' @noRd
app_ui <- function(request) {
  tagList(
    # Leave this function for adding external resources
    golem_add_external_resources(),
    # Your application UI logic
    navbarPage(
      title = "MADC FixedAlleleID Tool",
      theme = bslib::bs_theme(version = 5, bootswatch = "flatly"),
      id = "page",
      # Main processing module
      tabPanel(
        "Process MADC",
        mod_match_alleles_ui("match_alleles_1")
      ),
      # Database update module
      tabPanel(
        "Update DB",
        mod_update_db_ui("update_db_1")
      ),
      # Help tab
      tabPanel(
        "Help",
        p("Help documentation and instructions will be available here.")
      )
    )
  )
}

#' Add external Resources to the Application
#'
#' This function is internally used to add external
#' resources to the application.
#'
#' @import shiny
#' @importFrom golem add_resource_path activate_js favicon bundle_resources
#' @noRd
golem_add_external_resources <- function() {
  add_resource_path(
    "www",
    app_sys("app/www")
  )

  tags$head(
    favicon(),
    bundle_resources(
      path = app_sys("app/www"),
      app_title = "HapApp"
    ),
    # Add custom CSS
    tags$link(rel = "stylesheet", type = "text/css", href = "www/custom.css")
  )
}
