mod auth;
mod command;
mod config;
mod credential;
mod error;
mod output;
mod request;
mod storage;
use clap::Parser;
use command::{Action, Cli};
use error::{Error, Result};
use serde_json::Value;

fn run(cli: Cli) -> Result<Value> {
    if let Action::Commands { scope } = &cli.command {
        return command::discover(scope);
    }
    if let Action::Auth { action } = &cli.command {
        return auth::run(&cli, action);
    }
    if let Action::Schema(args) = &cli.command {
        command::business_path(&args.path)?;
        if cli.json.is_some()
            || cli.key.is_some()
            || cli.revision.is_some()
            || cli.fields.is_some()
            || !cli.query.is_empty()
            || cli.cursor.is_some()
        {
            return Err(Error::invalid(
                "Schema accepts only method, business path and connection options.",
            ));
        }
        let request = command::Request {
            method: "GET".into(),
            path: "/openapi.json".into(),
            query: vec![],
            body: None,
            key: None,
            shape: command::Shape::Other,
            list: false,
        };
        if cli.dry_run {
            return Ok(command::preview(&request));
        }
        let config = config::Config::load(&cli)?;
        let credential = credential::load(&config)?;
        let reply = request::send(&request::client()?, &config, &request, Some(&credential))?;
        return output::scoped_schema(reply.value, &args.method, &args.path);
    }
    let request = command::compile(&cli)?;
    let fields = output::validate_fields(&cli, &request)?;
    if cli.dry_run {
        return Ok(command::preview(&request));
    }
    let config = config::Config::load(&cli)?;
    let credential = credential::load(&config)?;
    let reply = request::send(&request::client()?, &config, &request, Some(&credential))?;
    output::format(&cli, &request, reply.value, &fields).map_err(|mut error| {
        if request.method != "GET" {
            error.mutation_confirmed = Some(true);
            error.delivery_unknown = Some(false);
            error.idempotency_key = request.key.clone();
        }
        error
    })
}

fn main() {
    let cli = match Cli::try_parse() {
        Ok(value) => value,
        Err(error)
            if matches!(
                error.kind(),
                clap::error::ErrorKind::DisplayHelp | clap::error::ErrorKind::DisplayVersion
            ) =>
        {
            let _ = error.print();
            return;
        }
        Err(_) => {
            let error = Error::invalid("Invalid arguments. Use bb --help or bb commands.");
            error.emit();
            std::process::exit(error.exit);
        }
    };
    match run(cli) {
        Ok(value) => println!("{value}"),
        Err(error) => {
            error.emit();
            std::process::exit(error.exit);
        }
    }
}
