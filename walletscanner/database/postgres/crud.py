# Side imports
from sqlalchemy import Numeric, select, update, delete, asc, desc, exists, case, cast, and_, or_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import ColumnElement
from asyncpg.exceptions import PostgresConnectionError, PostgresError
from asyncpg import Connection as AsyncpgConnection

import asyncio
import json
import functools
from typing import Any, Generic, TypeVar, Callable, Literal
from decimal import Decimal
from abc import ABC, abstractmethod

# Project imports
from walletscanner.core.logger import app_logger
from walletscanner.core.dependencies import SessionDep
from walletscanner.database.postgres.enums import TransactionType, AssetType
from walletscanner.core.exceptions import InstanceNotFoundException, InvalidFilteringParamsException
from walletscanner.database.postgres.models import Transaction, CoinBalance, ScanState


T = TypeVar("T", bound=DeclarativeBase)


class BaseCRUDService(Generic[T], ABC):
    """
    !interface
    The class implements core methods that simplify working with the SQLAlchemy ORM.

    Implements core methods for SQLAlchemy ORM. Eliminates the need for code repetition.
    Simplifies working with logical expressions. Execute CRUD-operations for any model within
    a single line. 
    To use its features, simply inherit your class from this one, overriding `model` field 
    and configuring the settings. Create your own methods or override existing ones 
    if the business logic needs to be changed. By default all database changes are not committed, 
    but flushed, so make sure to implement commitment somewhere else in your program. 
    Or you can set class variable `commit_on_change` to `True`, but it's not recommended to 
    do it this way to avoid unforeseen errors.

    :var: model             Your SQLAlchemy model you configure your crud-service for. Must be specified
    :var: commit_on_change  Determines if all changes have to be commited or just flushed. Defaults to `False` and it's highly recommended to leave it this way!
    :var: json_fields       Names of JSONB-type fields.
    :var: conflict_cols     Columns that can be conflicting. Must be specified. 
 
    :note: Is abstract (an interface)! You cannot create instances of this class. 
    :note: All methods that modify the state of a database are not committed, but flushed! 
    """
    commit_on_change: bool = False
    json_fields: list[str] | None = None

    def __init__(self, session: SessionDep) -> None:
        self.session = session

    @property
    @abstractmethod
    def model(self) -> type[T]:
        pass

    @property
    @abstractmethod
    def conflict_cols(self) -> list[str]:
        return ["id"]

    @property
    def all_columns(self) -> list[str]:
        return [c.name for c in self.model.__table__.columns]

    @property
    def required_columns(self) -> list[str]:
        return [
            c.name for c in self.model.__table__.columns
            if not (c.primary_key and c.autoincrement)
            and c.server_default is None
        ]
    
    @property
    def tablename(self) -> str:
        return self.model.__tablename__

    @staticmethod
    def _commit_changes(func):
        """
        Decorator to commit changes after the execution of state-modifying methods.
        Accepts an optional `commit` keyword override: pass `commit=False` to skip
        committing this specific call (useful when several calls must land in one
        atomic transaction), or `commit=True` to force a commit even if
        `self.commit_on_change` is False.
        """
        @functools.wraps(func)
        async def wrapper(self, *args, commit: bool | None = None, **kwargs):
            try:
                result = await func(self, *args, **kwargs)
                should_commit = commit if commit is not None else self.commit_on_change
                if should_commit:
                    await self.session.commit()
                return result
            except SQLAlchemyError:
                await self.session.rollback()
                raise
        return wrapper

    # BASIC CRUD
    # --------------------------------------------------------------------------------------------------

    # CREATE
    @_commit_changes
    async def add_one(self, **values: Any) -> T:
        """
        The universal method for adding a single instance to a table.

        Tries to add a single instance to a table. If some error 
        occurs, rollbacks the session and raises it. Returns created instance.

        :param values: Model fields with values.
        :type values: Any

        :return: Created instance.
        :rtype: T
        :raise: SQLAlchemyError Any SQLAlchemy error during data writing.
        """
        new_instance = self.model(**values)
        self.session.add(new_instance)
        await self.session.flush()
        return new_instance
    
    # CREATE
    @_commit_changes
    async def add_many(self, instances: list[dict[str, Any]]) -> list[T]:
        """
        The universal method for adding multiple instances to a table.

        Tries to add multiple instances to a table. If some error 
        occurs, rollbacks the session and raises it. Returns a list of created instances.

        :param instances: List of instances to add.
        :type instances: list[dict[str, Any]]

        :return: List of created instances.
        :rtype: list[T]
        :raise: SQLAlchemyError Any SQLAlchemy error during data writing.

        Example:
            >>> instances = [{"name" : "John", "age" : 25}, {"name" : "Alex", "age" : 30}]
            >>> await user_service.add_many(instances)
        """
        new_instances = [self.model(**values) for values in instances]
        self.session.add_all(new_instances)
        await self.session.flush()
        return new_instances
    
    # CREATE / UPDATE
    @_commit_changes
    async def upsert(self, update_cols: list[str], instances: list[dict[str, Any]] = None, chunk_size: int = 5000, **values: Any) -> None:
        """      
        The universal method for upserting (inserting and on conflict updating) multiple instances to a table.

        Tries to add multiple instances to a table. On unique constraint conflict updates the row. 
        If some error occurs, rollbacks the session and raises it. Does not return anything.

        :param instances: List of instances to add.
        :type instances: list[dict[str, Any]]  
        :param update_cols: List of columns to update if a conflict occurs.
        :type update_cols: list[str]
        :param values: Model fields with values.
        :type values: Any

        :return: None.
        :rtype: None
        :raise: SQLAlchemyError Any SQLAlchemy error during data writing.

        Example:
            >>> instances = [{"id" : 1, "name" : "John", "age" : 25, "status" : "admin"}, {"id" : 2, "name" : "Alex", "age" : 30, "status" : "user"}]
            >>> update_cols = ["status", "age"]
            >>> await user_service.upsert(update_cols, instances=instances)
        """
        if instances is not None and values:
            raise ValueError("Only one source of data must be specified: instances or **values!")
        upsert_values = values if values else instances
        if upsert_values is None:
            raise ValueError("No data was provided for the upsert operation (specify instances or kwargs)!")
        if not update_cols:
            raise ValueError("Fields that have to be updated must be specified!")
        
        batches = [upsert_values] if isinstance(upsert_values, dict) else [
            upsert_values[i:i + chunk_size] for i in range(0, len(upsert_values), chunk_size)
        ]

        for batch in batches:
            stmt = insert(self.model).values(batch)
            set_values = {}
            for col in update_cols:
                if col == "updated_at":
                    set_values["updated_at"] = func.now()
                else:
                    set_values[col] = stmt.excluded[col]
            stmt = stmt.on_conflict_do_update(
                index_elements=self.conflict_cols,
                set_=set_values
            )
            await self.session.execute(stmt)

        await self.session.flush()
            
    # READ
    async def get_one_by_pk(self, instance_id: Any) -> T | None:
        """
        The universal method for retrieving a single instance from a table by primary key.

        Retrieves a single instance from a table by its primary key. 
        Uses `session.get()` method. Does not raise any errors. Returns retrieved 
        instance or `None`.

        :param instance_id: Instance primary key.
        :type instance_id: Any
        
        :return: Retrieved instance.
        :rtype: T If instance was found.
        :rtype: None If there's no instance with such primary key.
        """
        instance = await self.session.get(self.model, instance_id) 
        return instance

    # READ
    async def get_one_by_filters(self, expr_func: Callable[[type[T]], ColumnElement[bool]]) -> T | None:
        """
        The universal method for retrieving a single (first) instance from a table by filters.

        Retrieves a single instance from a table that matches the clauses. 
        Uses `select().where()` function. Does not raise any errors. Returns retrieved 
        instance or `None`.

        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]]

        :return: First retrieved instance.
        :rtype: T If instance was found.
        :rtype: None If there're no instances satisfying such clauses.

        Example:
            >>> expr_func = lambda m: (m.age >= 18) & (m.gender == 'f')
            >>> await user_service.get_one_by_filters(expr_func)
        """
        sqla_expr = expr_func(self.model) if expr_func is not None else None
        query = select(self.model)
        if sqla_expr is not None:
            query = query.where(sqla_expr)
        result = await self.session.execute(query)
        return result.scalars().first()
    
    # READ
    async def get_many(self, 
        order_by: str = "id",
        sort_order: Literal["asc", "desc"] = "asc",
        page: int | None = None, 
        per_page: int | None = None, 
        expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None
    ) -> list[T]:
        """
        The universal method for retrieving multiple instances from a table. Supports ordering and where-clauses.

        Retrieves multiple instances from a table that match the clauses. 
        Returns a list of retrieved instances.

        :param order_by: field to order by
        :type order_by: str
        :param sort_order: sorting order
        :type sort_order: Literal["asc", "desc"]
        :param page: the page to start from
        :type page: int | None
        :param per_page: number of instances per page
        :type per_page: int | None
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: A list of retrieved instances matching the clauses
        :rtype: list[T]
        :raise: AttributeError: If non-existent field or an unknown sorting order was passed     
        """
        # Checking if we can sort by a passed field
        if not hasattr(self.model, order_by): 
            raise InvalidFilteringParamsException(f"Can not order by a non-existent field `{order_by}`!")
        # Checking if sort order is valid
        if sort_order not in ["asc", "desc"]:
             raise InvalidFilteringParamsException(f"Unknown sorting order ({sort_order})!")
        
        order_by_column = getattr(self.model, order_by)
        sort_by = desc(order_by_column) if sort_order == "desc" else asc(order_by_column)
        
        sqla_expr = expr_func(self.model) if expr_func is not None else None

        query = select(self.model)

        if sqla_expr is not None:
            query = query.where(sqla_expr)

        query = query.order_by(sort_by)

        if page and per_page:
            query= query.limit(per_page).offset((page - 1)*per_page)

        result = await self.session.execute(query)
        instances = result.scalars().all()
        return instances

    # UPDATE
    @_commit_changes
    async def update_instance_by_pk(self, instance_id: Any, values: dict[str, Any]) -> None:
        """
        The universal method for updating a single instance from a table by primary key.

        Updates a single instance from a table by its primary key. 
        Raises an error if there's no instance with corresponding primary key.
        Returns `None`.

        :param instance_id: Instance primary key.
        :type instance_id: Any
        :param values: Fields to update and their new values.
        :type values: dict[str, Any]

        :return: None
        :rtype: None
        :raise: SQLAlchemyError           Any SQLAlchemy error during data writing.
        :raise: InstanceNotFoundException If there's no instance with corresponding primary key
        """
        instance = await self.session.get(self.model, instance_id) 
        if not instance:
            raise InstanceNotFoundException
        for key, value in values.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        await self.session.flush()

    # UPDATE
    @_commit_changes
    async def update_many(self, values: dict[str, Any], expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None) -> int:
        """
        The universal method for updating multiple instances from a table. Supports clauses.

        Updates multiple instances from a table that match the clauses. 
        Returns the number of modified rows.

        :param values: New values for each instance
        :type values: dict[str, Any]
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None

        :return: Number of modified rows.
        :rtype: int
        :raise:  SQLAlchemyError: Any SQLAlchemy error during data writing.

        Example:
            >>> values = {"is_active" : False}
            >>> expr_func = lambda m: (m.subscription_id == 0) | (m.age < 18)
            >>> await user_service.update_many(values, expr_func)
        """
        sqla_expr = expr_func(self.model) if expr_func is not None else None
        query = update(self.model)
        if sqla_expr is not None:
            query = query.where(sqla_expr)
        query = query.values(**values)
        result = await self.session.execute(query)
        await self.session.flush()
        return result.rowcount

    # DELETE
    @_commit_changes
    async def delete_instance_by_pk(self, instance_id: Any) -> None:
        """
        The universal method for deleting a single instance from a table by primary key.

        Deletes a single instance from a table by its primary key. 
        Raises an error if there's no instance with corresponding primary key.
        Returns `None`.

        :param instance_id: Instance primary key.
        :type instance_id: Any

        :return: None
        :rtype: None
        :raise: InstanceNotFoundException If there's no instance with corresponding primary key
        """
        instance = await self.session.get(self.model, instance_id) 
        if not instance:
            raise InstanceNotFoundException
        await self.session.delete(instance)
        await self.session.flush()

    # DELETE   
    @_commit_changes 
    async def delete_many(self, expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None) -> int:
        """
        The universal method for deleting multiple instances from a table.

        Deletes multiple instances from a table that match the clauses. 
        Returns the number of deleted rows.

        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None

        :return: Number of deleted rows.
        :rtype: int

        Example:
            >>> expr_func = lambda m: (m.is_active == False) & (m.age >= 30)
            >>> await user_service.delete_many(expr_func)
        """
        sqla_expr = expr_func(self.model) if expr_func is not None else None
        query = delete(self.model)
        if sqla_expr is not None:
            query = query.where(sqla_expr)
        result = await self.session.execute(query)
        await self.session.flush()
        return result.rowcount
    
    async def exists(self, expr_func: Callable[[type[T]], ColumnElement[bool]]) -> bool:
        """
        The universal method for checking the existence of an instance meeting particular clauses.

        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]]

        :return: `True` if exists otherwise `False`
        :rtype: bool
        """
        sqla_expr = expr_func(self.model)
        query = select(exists().where(sqla_expr))
        result = await self.session.scalar(query)
        return result
    # --------------------------------------------------------------------------------------------------

    # AGGREGATE FUNCTIONS
    # --------------------------------------------------------------------------------------------------
    async def _aggregate_by(
        self, 
        func_element: Callable,  
        field_name: str, 
        group_by: str | None = None, 
        expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None
    ) -> Any:
        """
        The universal method for executing aggregation functions.
        
        :param field_name: The string name of the field used to calculate the sum.
        :type field_name: str
        :param group_by: The string name of the field to group by.
        :type group_by: str | None
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: Result of the function execution.
        :rtype: Any
        """
        field_name_column = getattr(self.model, field_name)
        sqla_expr = expr_func(self.model) if expr_func is not None else None
        if group_by:
            group_by_column = getattr(self.model, group_by)
            query = select(group_by_column, func_element(field_name_column))
        else:
            query = select(func_element(field_name_column))

        if sqla_expr is not None:
            query = query.where(sqla_expr)
            
        if group_by:
            query = query.group_by(group_by_column)
            result = await self.session.execute(query)
            return result.all()
        else:
            return await self.session.scalar(query)
        
    async def sum_by(
        self, 
        field_name: str, 
        group_by: str | None = None, 
        expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None
    ) -> Any:
        """
        The universal method for obtaining the sum of a field values. Supports clauses and grouping.
        
        :param field_name: The string name of the field used to calculate the sum.
        :type field_name: str
        :param group_by: The string name of the field to group by.
        :type group_by: str | None
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: The sum of a field values.
        :rtype: Any
        """
        result = await self._aggregate_by(func.sum, field_name, group_by, expr_func)
        return result


    async def avg_by(
        self, 
        field_name: str, 
        group_by: str | None = None, 
        expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None
    ) -> Any:
        """
        The universal method for obtaining the average value of a field. Supports clauses and grouping.
                
        :param field_name: The string name of the field used to calculate the average.
        :type field_name: str
        :param group_by: The string name of the field to group by.
        :type group_by: str | None
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: The average value.
        :rtype: Any
        """
        result = await self._aggregate_by(func.avg, field_name, group_by, expr_func)
        return result

    async def min_by(
        self, 
        field_name: str, 
        group_by: str | None = None, 
        expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None
    ) -> Any:
        """
        The universal method for obtaining the minimum value of a field. Supports clauses and grouping.
    
        :param field_name: The string name of the field used to calculate the average.
        :type field_name: str
        :param group_by: The string name of the field to group by.
        :type group_by: str | None
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: The minimum value.
        :rtype: Any
        """
        result = await self._aggregate_by(func.min, field_name, group_by, expr_func)
        return result

    async def max_by(
        self, 
        field_name: str, 
        group_by: str | None = None, 
        expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None
    ) -> Any:
        """
        The universal method for obtaining the maximum value of a field. Supports clauses and grouping.
    
        :param field_name: The string name of the field used to calculate the average.
        :type field_name: str
        :param group_by: The string name of the field to group by.
        :type group_by: str | None
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: The maximum value.
        :rtype: Any
        """
        result = await self._aggregate_by(func.max, field_name, group_by, expr_func)
        return result

    async def count_by(
        self, 
        field_name: str, 
        group_by: str | None = None, 
        expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None
    ) -> Any:
        """
        The universal method for obtaining the amount of rows. Supports clauses and grouping.

        :param field_name: The string name of the field used to count the amount of rows.
        :type field_name: str
        :param group_by: The string name of the field to group by.
        :type group_by: str | None
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: The amount of fields.
        :rtype: Any
        """
        result = await self._aggregate_by(func.count, field_name, group_by, expr_func)
        return result
    # --------------------------------------------------------------------------------------------------

    async def _get_asyncpg_conn(self) -> AsyncpgConnection:
        """
        The method retrieves a raw underlying `asyncpg` driver connection from the SQLAlchemy session.

        Extracts the lowest-level asynchronous connection from the active transaction context.
        This raw connection bypasses the SQLAlchemy ORM layer and compilation overhead, 
        which is critically required to perform ultra-high-speed binary `COPY` operations 
        directly into PostgreSQL.

        :return: Raw driver connection instance from `asyncpg`.
        :rtype: AsyncpgConnection
        :raise: SQLAlchemyError Any error during active session connection retrieval.
        """
        conn = await self.session.connection()
        raw_conn = await conn.get_raw_connection()
        return raw_conn.driver_connection
    

    async def _ensure_staging_table(self, conn: AsyncpgConnection) -> None:
        """
        The method prepares a temporary staging table in the database for bulk chunk inserts.

        Creates an isolated, non-transactional temporary table prefixed with `tmp_` based on 
        the schema of the target model. It dynamically retains all database-level column 
        defaults (e.g., timestamps and jsonb values), but explicitly detaches the primary key
        from the global sequence generator to prevent sequence leaks, ID skipping gaps, and schema locks.

        :param conn: Raw driver connection instance from `asyncpg`.
        :type conn: AsyncpgConnection

        :return: None.
        :rtype: None
        :raise: PostgresError Any native PostgreSQL error during table creation or modification.

        :note: Uses `INCLUDING DEFAULTS` statement but forcefully drops the auto-increment default 
               and NOT NULL constraint for the primary key column using `DROP DEFAULT` and `DROP NOT NULL` 
               to allow seamless binary streaming of records without sequence gaps or payload violations.
        :note: Automatically executes a `TRUNCATE` command at the end of initialization to ensure 
               the staging area is completely clean before processing a new chunk of blockchain logs.
        """     
        await conn.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS tmp_{self.tablename} "
            f"(LIKE {self.tablename} INCLUDING DEFAULTS) ON COMMIT PRESERVE ROWS"
        )

        # So that the date defaults remain, but the ID auto-increment in the temporary table is disabled.
        # To avoid `DependentObjectsStillExistError`
        pk_column_name = next(iter(self.model.__table__.primary_key.columns.keys()))

        await conn.execute(
            f"ALTER TABLE tmp_{self.tablename} "
            f"ALTER COLUMN {pk_column_name} DROP DEFAULT, "
            f"ALTER COLUMN {pk_column_name} DROP NOT NULL;"
        )
        await conn.execute(f"TRUNCATE tmp_{self.tablename}")


class TransactionsService(BaseCRUDService[Transaction]):
    model = Transaction
    commit_on_change = True
    json_fields = ["raw_log_args"]
    conflict_cols = ["transaction_hash", "log_index", "asset_id"]


    async def calculate_pusd_balance(self, address: str) -> int:
        """
        The method for calculating the USDT (pUSD) balance for an address
        
        :param address: wallet address.
        :type address: str

        :return: calculated pUSD balance.
        :rtype: int
        """
        balance_case = case(
            (self.model.from_address == address, -self.model.amount),
            (self.model.to_address == address, self.model.amount),
            else_=0
        )
        query = select(func.sum(balance_case)).where(self.model.asset_type == AssetType.PUSD)
        balance = await self.session.execute(query)
        result = balance.scalar()
        return result if result else 0
    
    
    async def calculate_token_balances(self, address: str) -> list[tuple[Decimal, int]]:
        """
        The method for calculating the balances of all tokens 
        ever bought and sold at an address. Includes "active" tokens only.

        :param address: wallet address.
        :type address: str

        :return: calculated balances of all purchased tokens.
        :rtype: list[tuple[Decimal, int]]
        """

        balance_case = case(
            (self.model.from_address == address, -self.model.amount),
            (self.model.to_address == address, self.model.amount),
            else_=0
        )
        all_token_balances_query = (
            select(
                self.model.asset_id.label("asset_id"),
                func.sum(balance_case).label("raw_balance")
            )
            .where(
                and_(
                    self.model.asset_type == AssetType.SHARE,
                    or_(
                        self.model.from_address == address,
                        self.model.to_address == address
                    )
                )
            )
            .group_by(self.model.asset_id)
        )

        all_token_balances = all_token_balances_query.cte(name="all_token_balances")
        lost_ids_json = self.model.raw_log_args["lost_asset_ids"]    
        unpacked_json = func.jsonb_array_elements_text(lost_ids_json)
        lost_id_numeric = cast(unpacked_json, Numeric(78, 0)).label("lost_id")

        lost_tokens_query = (
            select(lost_id_numeric)
            .where(
                and_(
                    self.model.transaction_type == TransactionType.REDEEM,
                    self.model.from_address == address,
                    self.model.raw_log_args["lost_asset_ids"].is_not(None)
                )
            )
            .distinct()
        )
        lost_tokens = lost_tokens_query.cte(name="blacklisted_assets")

        final_query = (
            select(all_token_balances.c.asset_id, all_token_balances.c.raw_balance)
            .select_from(all_token_balances)
            .join(lost_tokens, all_token_balances.c.asset_id == lost_tokens.c.lost_id, isouter=True)
            .where(
                and_(
                    all_token_balances.c.raw_balance > 0,
                    lost_tokens.c.lost_id.is_(None) 
                )
            )
        )
        result = await self.session.execute(final_query)
        return result.all()
    
    # CREATE
    async def add_many_raw(self, transactions: list[dict[str, Any]], chunk_size: int = 50000, max_retries: int = 3) -> None:
        """
        The universal high-speed method for bulk-inserting raw database records using binary streaming.

        Splits a list of dictionaries into optimal chunks, formats them into tuples, 
        and streams them into a temporary staging table via native `asyncpg.Connection.copy_records_to_table`. 
        Subsequently, executes an atomic `INSERT INTO ... SELECT` statement with an `ON CONFLICT DO NOTHING` 
        clause in order to deduplicate incoming blockchain logs based on configured unique constraints. 
        Supports exponential backoff retries.

        :param transactions: A comprehensive list of raw input records represented as dictionaries.
        :type transactions: list[dict[str, Any]]
        :param chunk_size: The maximum number of database records to batch insert in a single stream. Defaults to 50000.
        :type chunk_size: int
        :param max_retries: Total allowed network re-connection and chunk re-insertion attempts. Defaults to 3.
        :type max_retries: int

        :return: None.
        :rtype: None
        :raise: PostgresError Any uncaught native PostgreSQL data violation error.
        :raise: PostgresConnectionError If connection fails permanently after hitting maximum retry limits.

        :note: This method bypasses the standard SQLAlchemy ORM unit-of-work layer completely, 
               meaning database triggers, Python-level `@validates`, and standard ORM hooks are ignored.
        :note: Automatically sets up a specialized public `citext` to `text` type codec mapping on the 
               underlying driver to ensure case-insensitive Ethereum/Polymarket wallet address comparisons.
        :note: Safely cleans up and deallocates the staging infrastructure inside a robust `finally` 
               block using a structural `DROP TABLE` command to protect the VPS from memory and disk bloating.
        """
        raw_connection = await self._get_asyncpg_conn()
        await raw_connection.set_builtin_type_codec(
            "citext",
            codec_name="text",
            schema="public"
        )
        
        await self._ensure_staging_table(raw_connection)
        cols_sql = ", ".join(self.required_columns)
        conflict_cols_sql = ", ".join(self.conflict_cols)

        try:
            for i in range(0, len(transactions), chunk_size):
                chunk = transactions[i:i + chunk_size]
                records = list()

                for row in chunk:
                    row_to_add = list()
                    for col in self.required_columns:
                        if col in self.json_fields and row.get(col) is not None:
                            row_to_add.append(json.dumps(row[col]))
                        else:
                            row_to_add.append(row.get(col))
                    records.append(tuple(row_to_add))

                attempt = 0

                while True:
                    attempt += 1
                    try:
                        await raw_connection.copy_records_to_table(
                            f"tmp_{self.tablename}", records=records, columns=self.required_columns
                        )

                        await raw_connection.execute(f"""
                            INSERT INTO {self.tablename} ({cols_sql})
                            SELECT {cols_sql} FROM tmp_{self.tablename}
                            ON CONFLICT ({conflict_cols_sql}) DO NOTHING
                        """)

                        await raw_connection.execute(f"TRUNCATE tmp_{self.tablename}")
                        await self.session.commit()

                        app_logger.info(f"| SUCCESSFULLY WROTE CHUNK {i}:{i + chunk_size} |")

                        break

                    except (PostgresConnectionError, OSError, asyncio.TimeoutError) as e:
                        if attempt >= max_retries:
                            app_logger.error(f"Maximum retries amount reached! Stopping recording process.")
                            raise

                        await asyncio.sleep(2 ** attempt)
                        await self.session.rollback()
                        raw_connection = await self._get_asyncpg_conn()
                        await raw_connection.set_builtin_type_codec(
                            "citext",
                            codec_name="text",
                            schema="public"
                        )
                        await self._ensure_staging_table(raw_connection)
                        continue

                    except PostgresError as e:
                        app_logger.error(f"Uncaught error while writing raw data: {e}")
                        await self.session.rollback()
                        raise

        finally:
            await raw_connection.execute(f"DROP TABLE IF EXISTS tmp_{self.tablename};")


class CoinBalanceService(BaseCRUDService[CoinBalance]):
    model = CoinBalance
    commit_on_change = True
    conflict_cols = ["wallet_address", "asset_type", "asset_id"]


class ScanStateService(BaseCRUDService[ScanState]):
    model = ScanState
    commit_on_change = True
    conflict_cols = ["wallet_address"]
