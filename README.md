# TrekStor tablet activation server

This project restores the mandatory activation/customization flow used by old TrekStor tablets after the original service disappeared.

If you are interested in this project's backstory or technical details, read the blog post at [nikolan.net/posts/fixing-ipads/](https://nikolan.net/posts/fixing-ipads/).

Consider starring the repository if this helped you use your tablet again <3

## Components

### Server

The FastAPI server in `/server/` recreates the Setup Wizard's expected activation endpoints and returns a compatible configuration.

### Website

The static homepage in `/server/website/` is served by the FastAPI server at `/`. It also shows how many successful activation requests this service has handled.

### App

"Niko Was Here" is a tiny Android 4-compatible companion app located at `/nikowashere_src`. It uses a dark Holo interface, explains the project, shows basic device information, and can fetch the accompanying blog post from its RSS feed.

### PDF

The manual is a dark Holo-style PDF generated from Markdown at `/nikowashere_pdf`. It gives users a short explanation of why their tablet works again and links them to the full blog post.

## :3

This is an independent project. It is not affiliated with, endorsed by, sponsored by, or maintained by TrekStor or any successor to TrekStor. It does not include or redistribute TrekStor's original applications, firmware, or media.

For questions or inquiries, contact me at `niko@nikolan.net`.
