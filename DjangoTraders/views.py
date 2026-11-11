"""
Project-level views: the site home page, which also ends a login. There is no reliable way to detect a
browser closing, so a real POST (not just visiting the page) is what clears the session.
"""
from django.shortcuts import redirect, render


def home(request):
    """
    The site home page, linking into the djtraders app. A POST (the "start a new session" button) clears
    current_user and customer_id from the session; a GET asks for confirmation (home.html) while either is set.
    """
    if request.method == "POST":
        request.session.pop("current_user", None)
        request.session.pop("customer_id", None)
        return redirect("home")

    confirm_logout = bool(
        request.session.get("current_user") or request.session.get("customer_id")
    )

    # No "djtraders/" prefix: this template is found through TEMPLATES['DIRS'], not an app's templates/ folder.
    return render(request, "home.html", {"confirm_logout": confirm_logout})
