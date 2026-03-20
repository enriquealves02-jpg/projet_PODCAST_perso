// Google Apps Script — à coller dans Extensions > Apps Script du Google Sheet
// Puis : Déployer > Nouveau déploiement > Application Web > Accès : Tout le monde

function doGet(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

  var title = decodeURIComponent(e.parameter.title || "");
  var source = decodeURIComponent(e.parameter.source || "");
  var category = decodeURIComponent(e.parameter.category || "");
  var url = decodeURIComponent(e.parameter.url || "");
  var date = decodeURIComponent(e.parameter.date || "");
  var score = e.parameter.score || "";

  sheet.appendRow([date, title, source, category, url, score, new Date()]);

  var html = "<html><body style='font-family:sans-serif;text-align:center;padding:40px;'>"
    + "<h2>Merci Enrique !</h2>"
    + "<p>Tu as noté <strong>" + score + "/10</strong> :</p>"
    + "<p><em>" + title + "</em></p>"
    + "<p style='color:#888;margin-top:20px;'>Tu peux fermer cet onglet.</p>"
    + "</body></html>";

  return HtmlService.createHtmlOutput(html);
}
