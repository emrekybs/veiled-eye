"""Registry mapping module names to Celery task paths.

Each entry maps: route name -> (celery_task_path, pass_from)

``pass_from`` indicates whether the task accepts ``from_m`` as a second
argument.  Most modules only take ``(username,)``; a few take
``(username, from_m)``.
"""

# (celery_task_path, pass_from)
MODULE_REGISTRY: dict[str, tuple[str, bool]] = {
    "peopledatalabs": (
        "modules.peopledatalabs.peopledatalabs_tasks.t_peopledatalabs",
        False,
    ),
    "github": ("modules.github.github_tasks.t_github", True),
    "keybase": ("modules.keybase.keybase_tasks.t_keybase", True),
    "twitter": ("modules.twitter.twitter_tasks.t_twitter", False),
    "linkedin": ("modules.linkedin.linkedin_tasks.t_linkedin", True),
    "leaks": ("modules.leaks.leaks_tasks.t_leaks", False),
    "gitlab": ("modules.gitlab.gitlab_tasks.t_gitlab", False),
    "usersearch": (
        "modules.usersearch.usersearch_tasks.t_usersearch",
        False,
    ),
    "emailrep": ("modules.emailrep.emailrep_tasks.t_emailrep", False),
    "socialscan": (
        "modules.socialscan.socialscan_tasks.t_socialscan",
        False,
    ),
    "instagram": (
        "modules.instagram.instagram_tasks.t_instagram",
        True,
    ),
    "tiktok": ("modules.tiktok.tiktok_tasks.t_tiktok", False),
    "sherlock": ("modules.sherlock.sherlock_tasks.t_sherlock", False),
    "holehe": ("modules.holehe.holehe_tasks.t_holehe", False),
    "venmo": ("modules.venmo.venmo_tasks.t_venmo", False),
    "search": ("modules.search.search_tasks.t_search", False),
    "reddit": ("modules.reddit.reddit_tasks.t_reddit", False),
    "spotify": ("modules.spotify.spotify_tasks.t_spotify", False),
    "leaklookup": (
        "modules.leaklookup.leaklookup_tasks.t_leaklookup",
        False,
    ),
    "twitch": ("modules.twitch.twitch_tasks.t_twitch", False),
    "mastodon": ("modules.mastodon.mastodon_tasks.t_mastodon", False),
    "darkweb": ("modules.darkweb.darkweb_tasks.t_darkweb", False),
    "hudsonrock": (
        "modules.hudsonrock.hudsonrock_tasks.t_hudsonrock",
        False,
    ),
    "youtube": ("modules.youtube.youtube_tasks.t_youtube", False),
    # --- Extended modules (auto-chained, see factories/chain.py) ----------
    "maigret": ("modules.maigret.maigret_tasks.t_maigret", False),
    "userscanner": (
        "modules.userscanner.userscanner_tasks.t_userscanner",
        False,
    ),
    "darksherlock": (
        "modules.darksherlock.darksherlock_tasks.t_darksherlock",
        False,
    ),
    "gitsniff": ("modules.gitsniff.gitsniff_tasks.t_gitsniff", False),
    "crosslinked": (
        "modules.crosslinked.crosslinked_tasks.t_crosslinked",
        False,
    ),
    "crossref": ("modules.crossref.crossref_tasks.t_crossref", False),
    # --- Identity modules (SOCMIntelligence ports + native) -------------
    "telegram": ("modules.telegram.telegram_tasks.t_telegram", False),
    "gravatar": ("modules.gravatar.gravatar_tasks.t_gravatar", False),
    "steam": ("modules.steam.steam_tasks.t_steam", False),
    "bluesky": ("modules.bluesky.bluesky_tasks.t_bluesky", False),
    "hackernews": ("modules.hackernews.hackernews_tasks.t_hackernews", False),
    "stackexchange": (
        "modules.stackexchange.stackexchange_tasks.t_stackexchange",
        False,
    ),
    "kick": ("modules.kick.kick_tasks.t_kick", False),
    "snapchat": ("modules.snapchat.snapchat_tasks.t_snapchat", False),
    "wayback": ("modules.wayback.wayback_tasks.t_wayback", False),
    "whatsmyname": ("modules.whatsmyname.whatsmyname_tasks.t_whatsmyname", False),
    "pgp": ("modules.pgp.pgp_tasks.t_pgp", False),
    "phone": ("modules.phone.phone_tasks.t_phone", False),
    "crypto": ("modules.crypto.crypto_tasks.t_crypto", False),
    "emailreg": ("modules.emailreg.emailreg_tasks.t_emailreg", False),
    "domaininfo": ("modules.domaininfo.domaininfo_tasks.t_domaininfo", False),
    "ahmia": ("modules.ahmia.ahmia_tasks.t_ahmia", False),
}
