if($.cookie("css")) {
	$("link.theme").attr("href",$.cookie("css"));
}
$(document).ready(function() { 
	$("#styleSwitcher option").click(function() { 
		$("link.theme").attr("href",$(this).attr("rel"));
		$.cookie("css",$(this).attr("rel"), {expires: 365, path: '/'});
		return false;
	});
});