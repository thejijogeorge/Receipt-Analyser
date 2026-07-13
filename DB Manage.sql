USE master;
GO
ALTER DATABASE groceries_coles SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
ALTER DATABASE groceries_coles MODIFY NAME = [ExpenseAnalyser];
ALTER DATABASE [ExpenseAnalyser] SET MULTI_USER;
GO

USE [ExpenseAnalyser];
GO
DELETE FROM receipt_items;
DELETE FROM gift_cards;
DELETE FROM receipts;

-- optional: reset identity counters back to 1
DBCC CHECKIDENT ('receipt_items', RESEED, 0);
DBCC CHECKIDENT ('gift_cards', RESEED, 0);
DBCC CHECKIDENT ('receipts', RESEED, 0);