#!/usr/bin/env python3
import os
import singer
from singer import metadata, utils
from singer.catalog import Catalog, CatalogEntry, Schema
from . import streams as streams
from .streams import (
    all_streams,
    all_stream_ids,
    sub_stream_ids,
    has_sub_stream_ids,
    sub_stream_suffix,
)
from .client import XeroClient
from .context import Context

REQUIRED_CONFIG_KEYS = [
    "start_date",
    "client_id",
    "client_secret",
    "tenant_id",
    "refresh_token",
]

LOGGER = singer.get_logger()

BAD_CREDS_MESSAGE = """
    Failed to refresh OAuth token. The token might need to be reauthorized from the integration's properties or there could be another authentication issue. Please attempt to reauthorize the integration.
"""


def get_abs_path(path):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)


def load_schema(tap_stream_id):
    path = "schemas/{}.json".format(tap_stream_id)
    schema = utils.load_json(get_abs_path(path))
    dependencies = schema.pop("tap_schema_dependencies", [])
    refs = {}
    for sub_stream_id in dependencies:
        refs[sub_stream_id] = load_schema(sub_stream_id)
    if refs:
        singer.resolve_schema_references(schema, refs)
    return schema


def load_metadata(stream, schema):
    mdata = metadata.new()

    mdata = metadata.write(mdata, (), "table-key-properties", stream.pk_fields)
    mdata = metadata.write(
        mdata, (), "forced-replication-method", stream.replication_method
    )

    if stream.bookmark_key:
        mdata = metadata.write(
            mdata, (), "valid-replication-keys", [stream.bookmark_key]
        )

    for field_name in schema["properties"].keys():
        if field_name in stream.pk_fields or field_name == stream.bookmark_key:
            mdata = metadata.write(
                mdata, ("properties", field_name), "inclusion", "automatic"
            )
        else:
            mdata = metadata.write(
                mdata, ("properties", field_name), "inclusion", "available"
            )

    return metadata.to_list(mdata)


def ensure_credentials_are_valid(config):
    XeroClient(config).fetch("currencies")


def load_correct_schema(stream_id):
    return (
        load_schema(stream_id)
        if not stream_id.endswith(sub_stream_suffix) or "journals" in stream_id
        else load_schema("line_items")
    )


def discover(ctx):
    ctx.refresh_credentials()
    catalog = Catalog([])
    for stream in streams.all_streams:
        schema_dict = load_correct_schema(stream.tap_stream_id)
        mdata = load_metadata(stream, schema_dict)

        schema = Schema.from_dict(schema_dict)
        catalog.streams.append(
            CatalogEntry(
                stream=stream.tap_stream_id,
                tap_stream_id=stream.tap_stream_id,
                key_properties=stream.pk_fields,
                schema=schema,
                metadata=mdata,
            )
        )
    return catalog


def load_and_write_schema(stream):
    singer.write_schema(
        stream.tap_stream_id,
        load_correct_schema(stream.tap_stream_id),
        stream.pk_fields,
    )


def sync(ctx):
    ctx.refresh_credentials()
    stream_ids_to_sync = {
        cs.tap_stream_id for cs in ctx.catalog.streams if cs.is_selected()
    }

    streams = [s for s in all_streams if s.tap_stream_id in stream_ids_to_sync]
    subs_dict = {
        s.tap_stream_id: s
        for s in streams
        if s.tap_stream_id in sub_stream_ids and s.tap_stream_id in stream_ids_to_sync
    }
    for stream in streams:
        stream_id = stream.tap_stream_id

        # sub-stream IDs will be synced by parent stream
        if stream_id in sub_stream_ids:
            continue

        ctx.write_state()
        load_and_write_schema(stream)

        sub = (
            subs_dict.get(stream_id + sub_stream_suffix)
            if stream_id in has_sub_stream_ids
            else None
        )
        if sub:
            load_and_write_schema(sub)

        LOGGER.info("Syncing stream: %s", stream_id)
        stream.sync(ctx, sub)


def main_impl():
    args = utils.parse_args(REQUIRED_CONFIG_KEYS)
    if args.discover:
        discover(Context(args.config, {}, {})).dump()
        print()
    else:
        catalog = (
            Catalog.from_dict(args.properties)
            if args.properties
            else discover(Context(args.config, {}, {}))
        )
        sync(Context(args.config, args.state, catalog))


def main():
    try:
        main_impl()
    except Exception as exc:
        LOGGER.critical(exc)
        raise exc


if __name__ == "__main__":
    main()
