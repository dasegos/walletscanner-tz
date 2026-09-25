# Side imports
from sqlalchemy import Numeric, select, update, delete, asc, desc, exists, case, cast, and_, or_, func
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import ColumnElement

import functools
from typing import Any, Generic, TypeVar, Callable, Literal
from decimal import Decimal
from abc import ABC, abstractmethod

# Project imports
from walletscanner.database.postgres.engine import SessionDep
from walletscanner.database.postgres.enums import TransactionType, AssetType
from walletscanner.core.exceptions import InstanceNotFoundException, InvalidFilteringParamsException
from walletscanner.database.postgres.models import Transaction, CoinBalance


T = TypeVar("T", bound=DeclarativeBase)


class BaseCRUDService(Generic[T], ABC):
    """
    !interface
    The class implements core methods that simplify working with the SQLAlchemy ORM.

    Implements core methods for SQLAlchemy ORM. Eliminates the need for code repetition.
    Simplifies working with logical expressions. Execute CRUD-operations for any model within
    a single line. Don't overwrite code for basic operation from project to project.
    To use its features, simply inherit your class from this one, overriding `__init__` method 
    and configuring the settings. Create your own methods or override existing ones 
    if the business logic needs to be changed. By default all database changes are not committed, 
    but flushed, so make sure to implement commitment somewhere else in your program. 
    Or you can set class variable `commit_on_change` to `True`, but it's not recommended to 
    do it this way to avoid unforeseen errors.

    :var: model             Your SQLAlchemy model you configure your crud-service for.
    :var: commit_on_change  Determines if all changes have to be commited or just flushed. Defaults to `False` and it's highly recommended to leave it this way!
 
    :note: Is abstract (an interface)! You cannot create instances of this class. 
    :note: All methods that modify the state of a database are not committed, but flushed! 
    :note: Make sure to override the `__init__` method in the subclasses

    Example:
        >>> class UserService(BaseCRUDService[User]):
        >>>     model = User
        >>>     ... # other settings
        >>>     ...
        >>>     def __init__(self, *args, **kwargs):  # must be implemented
        >>>         super().__init__(*args, **kwargs)
    """
    model: type[T] = None 
    commit_on_change: bool = False


    @abstractmethod
    def __init__(self, session: SessionDep) -> None:
        self.session = session


    @staticmethod
    def _commit_changes(func):
        """
        Decorator to commit changes after the execution of state-modifying methods.
        """
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):   
            result = await func(self, *args, **kwargs)
            if self.commit_on_change:
                await self.session.commit()  
            return result    
        return wrapper

    
    # BASIC CRUD
    # ====================================================================================================

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
        try:
            self.session.add(new_instance)
            await self.session.flush()
        except SQLAlchemyError as e:
            await self.session.rollback()
            raise e
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
        :raise:  SQLAlchemyError Any SQLAlchemy error during data writing.

        Example:
            >>> instances = [{"name" : "John", "age" : 25}, {"name" : "Alex", "age" : 30}]
            >>> await user_service.add_many(instances)
        """
        new_instances = [self.model(**values) for values in instances]
        try:
            self.session.add_all(new_instances)
            await self.session.flush()
        except SQLAlchemyError as e:
            await self.session.rollback()
            raise e
        return new_instances
    
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
            >>> expr_func = lambda m: m.age >= 18 & m.gender == 'f'
            >>> await user_service.get_one_by_filters(expr_func)
        """
        sqla_expr = expr_func(self.model)
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
        
        sort_by = desc(order_by) if sort_order == "desc" else asc(order_by)
        sqla_expr = expr_func(self.model)
        query = select(self.model).where(sqla_expr).order_by(sort_by)

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
        try:
            instance = await self.session.get(self.model, instance_id) 
            if not instance:
                raise InstanceNotFoundException
            for key, value in values.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            await self.session.flush()
        except SQLAlchemyError as e:
            await self.session.rollback()
            raise e
        
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
            >>> expr_func = lambda m: m.subscription_id == 0 | m.age < 18
            >>> await user_service.update_many(values, expr_func)
        """
        try:
            sqla_expr = expr_func(self.model)
            query = update(self.model).where(sqla_expr).values(**values)
            result = await self.session.execute(query)
            await self.session.flush()
            return result.rowcount
        except SQLAlchemyError as e:
            await self.session.rollback()
            raise e
        
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
            >>> expr_func = lambda m: m.is_active == False & m.age >= 30
            >>> await user_service.delete_many(expr_func)
        """
        sqla_expr = expr_func(self.model)
        query = delete(self.model).where(sqla_expr)
        result = await self.session.execute(query)
        await self.session.flush()
        return result.rowcount
    
    async def exists(self, expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None) -> bool:
        """
        The universal method for checking the existence of an instance meeting particular clauses.

        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None

        :return: `True` if exists otherwise `False`
        :rtype: bool
        """
        sqla_expr = expr_func(self.model)
        query = select(exists().where(sqla_expr))
        result = await self.session.scalar(query)
        return result

    # AGGREGATE FUNCTIONS
    # ====================================================================================================
    async def sum_by(self, field_name: str, expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None) -> float:
        """
        The universal method for obtaining the sum of a field values.
        
        Obtains the sum of a field values. Supports clauses and grouping.

        :param field_name: The string name of the field used to calculate the sum.
        :type field_name: str
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: The sum of a field values.
        :rtype: float
        """
        sqla_expr = expr_func(self.model)
        query = select(func.sum(field_name)).where(sqla_expr)
        result = await self.session.scalar(query)
        if result:
            return result
        return 0.0


    async def avg_by(self, field_name: str, group_by: str | None = None, expr_func: Callable[[type[T]], ColumnElement[bool]] | None = None) -> float:
        """
        The universal method for obtaining the average value of a field.

        Obtains the average value of a field. Supports clauses and grouping.

        :param field_name: The string name of the field used to calculate the average.
        :type field_name: str
        :param group_by: The string name of the field to group by.
        :type group_by: str
        :param expr_func: Lambda-function that takes a class and returns an SQLAlchemy boolean expression.
        :type expr_func: Callable[[type[T]], ColumnElement[bool]] | None
        
        :return: The average value of a field.
        :rtype: float
        """
        sqla_expr = expr_func(self.model)
        query = select(func.avg(field_name)).where(sqla_expr).group_by(group_by)
        result = await self.session.scalar(query)
        return result


class TransactionsService(BaseCRUDService[Transaction]):
    model = Transaction

    def __init__(self, session: SessionDep) -> None:
        self.session = session

    async def calculate_pusd_balance(self, address: str) -> int:
        """
        The method for calculating the 
        USDT (pUSD) balance for an address
        
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
        query = select(func.sum(balance_case)).where(self.model.asset_type == AssetType.USDT)
        balance = await self.session.execute(query)
        return balance.scalar()
    
    
    async def calculate_token_balances(self, address: str) -> list[tuple[Decimal, int]]:
        """
        The method for calculating the balances of 
        all tokens ever bought and sold at an address.
        Includes "active" tokens only.

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
                    self.model.raw_log_args["lost_asset_ids"] != None
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
                    lost_tokens.c.lost_id == None  
                )
            )
        )

        result = await self.session.execute(final_query)

        return result


class CoinBalanceService(BaseCRUDService[CoinBalance]):
    model = CoinBalance

    def __init__(self, session: SessionDep) -> None:
        self.session = session