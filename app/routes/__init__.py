"""路由包。"""

from . import emails, groups, jobs_api, mailboxes, pages, settings_api


def register_blueprints(app) -> None:
    app.register_blueprint(pages.bp)
    app.register_blueprint(groups.bp)
    app.register_blueprint(mailboxes.bp)
    app.register_blueprint(emails.bp)
    app.register_blueprint(jobs_api.bp)
    app.register_blueprint(settings_api.bp)
