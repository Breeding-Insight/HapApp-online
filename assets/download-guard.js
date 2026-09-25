// Ask for confirmation before leaving the page while a shared download is being prepared.
window.addEventListener("beforeunload", function (event) {
  if (document.getElementById("madc-download-progress-modal")) {
    event.preventDefault();
    event.returnValue = "";
  }
});
