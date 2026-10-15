"""
version: 3.2.0
author: Wuyilingwei
Main script for the mod data update tool
Focus: Fetch new mods, download them, and update TOML data files
Translation handled by cloud workflow, but git operations for data repository remain
Single-version tracking: Only keep latest version, merge unique keys from older versions
Target utils version:
workshop: 1.0.x
config: 1.0.x
file: 3.0.x
steamcmd: 1.0.x
helper: 1.0.x
mod_target: 3.1.x
git: 1.0.x
"""
from util.workshop import *
from util.config import *
from util.file import *
from util.steamcmd import *
from util.helper import *
from util.git import *
from util.mod_target import ModTarget
from util.reorder import batch_download_with_delay
import argparse
import logging
import os
import time


def parse_args():
    parser = argparse.ArgumentParser(description="Timberborn Mod Data Update Tool")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip Step 1: fetching new mods from Steam Workshop")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip Step 2: downloading mods via SteamCMD")
    parser.add_argument("--start-from", type=int, choices=[1, 2, 3, 4, 5, 6], default=0,
                        help="Start from a specific step (1-6). Implies skipping prior steps.")
    parser.add_argument("--batch-size", type=int, default=5,
                        help="Number of mods per batch download (default: 5)")
    parser.add_argument("--batch-delay", type=int, default=5,
                        help="Minutes to wait between batch downloads (default: 5)")
    parser.add_argument("--use-api", action="store_true",
                        help="Use Steam Web API (IPublishedFileService) instead of web scraping")
    parser.add_argument("--incremental", action="store_true",
                        help="(API mode) Only fetch newly updated mods not already in config")
    parser.add_argument("--api-limit", type=int, default=0,
                        help="(API mode) Max mods to fetch per run (overrides config)")
    parser.add_argument("--api-max-pages", type=int, default=0,
                        help="(API mode) Max pages to fetch (default: 10 full, 3 incremental)")
    parser.add_argument("--days", type=int, default=0,
                        help="(Scrape mode) Only include mods updated within N days (0 = use config value)")
    parser.add_argument("--depth", type=int, default=0,
                        help="(Scrape mode) Number of Workshop pages to scan (0 = use config value)")
    return parser.parse_args()


def skip_step(step_num, args):
    if args.start_from > step_num:
        return True
    if step_num == 1 and args.skip_fetch:
        return True
    if step_num == 2 and args.skip_download:
        return True
    return False


CONFIG_CHANGED = False


def main():
    args = parse_args()
    global CONFIG_CHANGED

    # Step 0: Initialize paths and configuration
    workpath = os.getcwd()
    config = Config(os.path.join(workpath, "config.toml"))
    game_mod_path = os.path.join(workpath, "steamcmd", "steamapps", "workshop", "content", str(config["workshop"]["game_id"]))

    # Setup git paths
    git_path = os.path.join(workpath, "git")
    if not os.path.exists(git_path):
        os.makedirs(git_path)
    if config["git"]["enabled"]:
        git = Git(git_path, config["git"]["branch"])
    data_path = os.path.join(git_path, "data")
    if not os.path.exists(data_path):
        os.makedirs(data_path)

    # Setup logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(config["common"]["logPath"], encoding='utf-8')
    file_handler.setLevel(config["common"]["fileLevel"])
    file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(config["common"]["consoleLevel"])
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("=" * 80)
    logger.info("Timberborn Mod Data Update Tool v3.2")
    logger.info(f"CLI args: fetch={not skip_step(1, args)}, download={not skip_step(2, args)}, "
                f"start_from={args.start_from or 'N/A'}, use_api={args.use_api}, "
                f"incremental={args.incremental}, days={args.days or config['workshop'].get('days', 'N/A')}")
    logger.info("Single-version tracking with old version key merging")
    logger.info("=" * 80)

    if config["git"]["enabled"]:
        logger.info("Step 0: Synchronizing data repository to cloud state...")
        git.sync()

    # Step 1: Fetch new mods from Steam Workshop
    if skip_step(1, args):
        logger.info("Step 1: SKIPPED (fetching new mods)")
    else:
        use_api = args.use_api or config["workshop"].get("api_mode", False)
        if use_api:
            logger.info("Step 1: Fetching mods via Steam Web API (IPublishedFileService)...")
            api_key = config["steam"].get("api_key", "")
            if not api_key:
                logger.error("Steam API key not configured — set [steam].api_key in config.toml")
                logger.warning("Falling back to web scraping")
                use_api = False

        if use_api:
            api = SteamAPIWorkshop(
                api_key=config["steam"]["api_key"],
                game_id=config["workshop"]["game_id"],
                text=config["workshop"]["text"],
            )

            api_days = args.days if args.days > 0 else config["workshop"].get("days", -1)

            if args.incremental:
                # Incremental mode: only get newly updated mods
                api_limit = args.api_limit or config["workshop"].get("api_limit", 200)
                max_pages = args.api_max_pages or 3
                logger.info(
                    f"Incremental mode: fetching up to {api_limit} mods, "
                    f"max {max_pages} pages, days={api_days}"
                )
                new_mod_ids = api.get_incremental_mods(
                    existing_ids=config["workshop"]["ids"],
                    max_pages=max_pages,
                    numperpage=min(api_limit, 100),
                    days=api_days,
                )
            else:
                # Full fetch mode: get all mods sorted by last update
                api_limit = args.api_limit or config["workshop"].get("api_limit", 200)
                max_pages = args.api_max_pages or 10
                logger.info(
                    f"Full fetch mode: up to {api_limit} mods, "
                    f"max {max_pages} pages, days={api_days}"
                )
                all_api_ids = api.get_all_mod_ids(
                    max_pages=max_pages,
                    numperpage=min(api_limit, 100),
                    days=api_days,
                )
                new_mod_ids = [
                    mid for mid in all_api_ids
                    if mid not in config["workshop"]["ids"]
                ]

            new_mod_count = 0
            for mod_id in new_mod_ids:
                if mod_id not in config["workshop"]["ids"]:
                    config["workshop"]["ids"].append(mod_id)
                    new_mod_count += 1
                    logger.info(f"New mod found via API: {mod_id}")

            logger.info(
                f"API mode: {new_mod_count} new mods found "
                f"(total tracked: {len(config['workshop']['ids'])})"
            )
            if new_mod_count > 0:
                CONFIG_CHANGED = True
        else:
            # Original web scraping mode
            logger.info("Step 1: Fetching latest mods via web scraping...")
            days = args.days if args.days > 0 else config["workshop"].get("days", -1)
            depth = args.depth if args.depth > 0 else config["workshop"]["depth"]
            workshop = WorkshopNewMods(config["workshop"]["game_id"], config["workshop"]["text"])
            new_mods = workshop.get_mods(depth, days=days)

            new_mod_count = 0
            for mod_id in new_mods:
                if mod_id not in config["workshop"]["ids"]:
                    config["workshop"]["ids"].append(mod_id)
                    new_mod_count += 1
                    logger.info(f"New mod found: {mod_id}")
            logger.info(f"Found {new_mod_count} new mods")
            if new_mod_count > 0:
                CONFIG_CHANGED = True

    # Remove blacklisted mods
    for black_id in config["workshop"]["blacklist_ids"]:
        if black_id in config["workshop"]["ids"]:
            config["workshop"]["ids"].remove(black_id)
            logger.info(f"Mod {black_id} is blacklisted and removed from the list")

    logger.info(f"Total mods to process: {len(config['workshop']['ids'])}")

    # Step 2: Download mods (new / missing local files / updated on Steam)
    if skip_step(2, args):
        logger.info("Step 2: SKIPPED (downloading mods)")
    else:
        logger.info("Step 2: Checking mods for required downloads (missing + Steam updates)...")
        steamClient = steamdownloader(config["steam"]["username"], os.path.join(workpath, "steamcmd"))

        # Query Steam for latest update timestamps of all tracked mods (no API key needed)
        steam_times = get_published_file_details(config["workshop"]["ids"])

        days = args.days if args.days > 0 else config["workshop"].get("days", -1)
        current_time = time.time()

        ids_to_download = []
        missing_count = 0
        update_count = 0

        for mod_id in config["workshop"]["ids"]:
            mod_path = os.path.join(game_mod_path, mod_id)
            ws_json = os.path.join(mod_path, "workshop_data.json")
            en_csv = os.path.join(mod_path, "Localizations", "enUS.csv")
            local_exists = os.path.exists(ws_json) or os.path.exists(en_csv)

            if not local_exists:
                logger.info(f"Mod {mod_id}: missing local files, queued for download")
                ids_to_download.append(mod_id)
                missing_count += 1
            elif mod_id in steam_times:
                steam_time = steam_times[mod_id]
                local_file = ws_json if os.path.exists(ws_json) else en_csv
                local_mtime = os.path.getmtime(local_file)
                steam_is_newer = steam_time > local_mtime
                within_window = days <= 0 or (current_time - steam_time) < days * 86400
                if steam_is_newer and within_window:
                    logger.info(f"Mod {mod_id}: Steam update detected, queued for re-download")
                    ids_to_download.append(mod_id)
                    update_count += 1
                else:
                    logger.debug(f"Mod {mod_id}: up to date, skipping")

        logger.info(f"Download queue: {len(ids_to_download)} mods "
                    f"({missing_count} missing, {update_count} updated on Steam)")

        if ids_to_download:
            batch_download_with_delay(
                steamClient,
                config["workshop"]["game_id"],
                ids_to_download,
                batch_size=args.batch_size,
                delay_minutes=args.batch_delay,
            )
        else:
            logger.info("All mods are up to date, nothing to download")

    # Step 3: Create ModTarget instances for each mod
    logger.info("Step 3: Creating mod targets...")
    mod_targets = {}
    valid_mod_ids = []
    total_ids = len(config["workshop"]["ids"])

    for idx, id in enumerate(config["workshop"]["ids"]):
        try:
            if idx % 50 == 0:
                logger.info(f"Step 3 progress: {idx}/{total_ids}")
            mod_path = os.path.join(game_mod_path, id)

            # Skip mods that don't exist on disk (never downloaded)
            if not os.path.exists(mod_path):
                logger.warning(f"Mod {id} directory not found, skipping")
                continue

            mod_name = parse_mod_info(os.path.join(mod_path, "workshop_data.json"))
            versions = search_versions(mod_path)
            if not versions:
                logger.warning(f"Mod {id} has no version subdirectories, skipping")
                continue
            support_versions = search_file(mod_path, versions, keyword="en")

            if support_versions is None or not support_versions:
                logger.warning(f"Mod {id} cannot find any translation files")
                continue

            mod_target = ModTarget(
                mod_id=id,
                mod_name=mod_name,
                mod_path=mod_path
            )

            for support_version, raw_file_path in support_versions.items():
                if raw_file_path is None:
                    continue
                if mod_target.add_version(support_version, raw_file_path):
                    logger.info(f"Added version {support_version} for mod {id}")

            if mod_target.has_valid_versions():
                mod_targets[id] = mod_target
                valid_mod_ids.append(id)
            else:
                logger.warning(f"Mod {id} has no valid versions")
        except Exception as e:
            logger.error(f"Error creating mod target for mod {id}: {e}")

    logger.info(f"Step 3 complete: {len(valid_mod_ids)}/{total_ids} mods loaded")

    # Update config with only valid mod IDs
    config["workshop"]["ids"] = valid_mod_ids

    # Step 4: Process each ModTarget to update data
    logger.info("Step 4: Updating TOML data files...")
    processed_count = 0
    error_count = 0
    step4_total = len(mod_targets)

    for idx, (mod_id, mod_target) in enumerate(mod_targets.items()):
        try:
            if idx % 20 == 0:
                logger.info(f"Step 4 progress: {idx}/{step4_total}")
            logger.info(f"Processing mod {mod_id}: {mod_target.mod_name}")

            mod_target.load_old_data(data_path)
            mod_target.update_all_data()
            mod_target.save_all_data(data_path)

            processed_count += 1
        except Exception as e:
            logger.error(f"Error processing mod {mod_id}: {e}")
            error_count += 1

    logger.info(f"Step 4 complete: {processed_count} processed, {error_count} errors")

    # Step 5: Save configuration
    logger.info("Step 5: Saving configuration...")
    config.save_config()

    # Step 6: Push data repository if git enabled
    if config["git"]["enabled"]:
        logger.info("Step 6: Pushing updated data to repository...")
        git.push()

    # Summary
    logger.info("=" * 80)
    logger.info("Processing complete!")
    logger.info(f"Mods processed: {processed_count}")
    logger.info(f"Errors: {error_count}")
    logger.info(f"Data files saved to: {data_path}")
    logger.info("Next: Cloud workflow will handle translation and publishing")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
