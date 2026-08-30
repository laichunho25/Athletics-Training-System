"""公開報名頁面：項目列表 → 項目詳情／報名表 → 完成頁。"""

from django.shortcuts import get_object_or_404, redirect, render

from programs.forms import ApplicationForm
from programs.models import Application, ApplicationStatus, Project, ProjectStatus


def _public_projects():
    return Project.objects.filter(
        status__in=[ProjectStatus.OPEN, ProjectStatus.CLOSED]
    ).order_by("display_order", "-start_date")


def project_list(request):
    projects = list(_public_projects())
    return render(
        request,
        "programs/list.html",
        {
            "projects": projects,
            "open_projects": [p for p in projects if p.is_accepting],
        },
    )


def project_detail(request, slug):
    project = get_object_or_404(_public_projects(), slug=slug)
    accepting, reason = project.accepting_reason()
    return render(
        request,
        "programs/detail.html",
        {"project": project, "accepting": accepting, "closed_reason": reason},
    )


def apply_view(request, slug):
    project = get_object_or_404(_public_projects(), slug=slug)
    accepting, reason = project.accepting_reason()
    if not accepting:
        return render(
            request,
            "programs/closed.html",
            {"project": project, "closed_reason": reason},
            status=403,
        )

    if request.method == "POST":
        form = ApplicationForm(request.POST, project=project)
        if form.is_valid():
            application = form.save(commit=False)
            application.project = project
            # 額滿後仍收表，但直接標成候補，不佔正取名額
            application.status = (
                ApplicationStatus.WAITLIST if project.is_full else ApplicationStatus.NEW
            )
            application.save()
            request.session["application_id"] = application.pk
            return redirect("programs:done", slug=project.slug)
    else:
        form = ApplicationForm(project=project)

    return render(
        request,
        "programs/apply.html",
        {"project": project, "form": form, "is_full": project.is_full},
    )


def apply_done(request, slug):
    project = get_object_or_404(_public_projects(), slug=slug)
    application = Application.objects.filter(
        pk=request.session.get("application_id"), project=project
    ).first()
    return render(
        request,
        "programs/done.html",
        {"project": project, "application": application},
    )
